from abc import ABC,abstractmethod
from contextlib import contextmanager
from dflow.python import (
    OP,
    OPIO,
    OPIOSign,
    Artifact,
    TransientError,
    FatalError,
    BigParameter,
    Parameter,
)
from dflow import (
    Workflow,
    Step,
    upload_artifact,
    download_artifact,
    InputArtifact,
    OutputArtifact,
    ShellOPTemplate
)
import os, json, dpdata, shutil
from pathlib import Path
from typing import (
    Any,
    Tuple,
    List,
    Set,
    Dict,
    Optional,
    Union,
)
import numpy as np
import dargs
from dargs import (
    dargs,
    Argument,
    Variant,
    ArgumentEncoder,
)

@contextmanager
def set_directory(path: Path):
    '''Sets the current working path within the context.
    Parameters
    ----------
    path : Path
        The path to the cwd
    Yields
    ------
    None
    Examples
    --------
    >>> with set_directory("some_path"):
    ...    do_something()
    '''
    cwd = Path().absolute()
    path.mkdir(exist_ok=True, parents=True)
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(cwd)

class RunFp(OP, ABC):
    r'''Execute a first-principles (FP) task.
    A working directory named `task_name` is created. All input files
    are copied or symbol linked to directory `task_name`. The FP
    command is exectuted from directory `task_name`. 
    '''

    @classmethod
    def get_input_sign(cls):
        return OPIOSign(
            {
                "task_name": str,
                "task_path": Artifact(Path),
                "backward_list": List[str],
                "log_name": Parameter(str,default='log'),
                "backward_dir_name": Parameter(str,default='backward_dir'),
                "config": BigParameter(dict,default={}),
                "optional_artifact": Artifact(Dict[str,Path],optional=True),
                "optional_input": BigParameter(dict,default={})
            }
        )

    @classmethod
    def get_output_sign(cls):
        return OPIOSign(
            {
                "backward_dir": Artifact(Path),
            }
        )

    @abstractmethod
    def input_files(self) -> List[str]:
        r'''The mandatory input files to run a FP task.
        Returns
        -------
        files: List[str]
            A list of madatory input files names.
        '''
        pass

    @abstractmethod
    def run_task(
        self,
        backward_dir_name,
        log_name,
        backward_list: List[str],
        run_config: Optional[Dict]=None,
        optional_input: Optional[Dict]=None,
    ) -> str:
        r'''Defines how one FP task runs
        Parameters
        ----------
        backward_dir_name:
            The name of the directory which contains the backward files.
        log_name:
            The name of log file.
        backward_list:
            The output files the users need.
        run_config:
            Keyword args defined by the developer.
            The fp/run_config session of the input file will be passed to this function.
        optional_input:
            The parameters developers need in runtime.
        
        Returns
        -------
        backward_dir_name: str
            The directory name which containers the files users need.
        '''
        pass

    @staticmethod
    @abstractmethod
    def args() -> List[dargs.Argument]:
        r'''The argument definition of the `run_task` method.
        Returns
        -------
        arguments: List[dargs.Argument]
            List of dargs.Argument defines the arguments of `run_task` method.
        '''
        pass

    @classmethod
    def normalize_config(cls, data: Dict = {}, strict: bool = True) -> Dict:
        r'''Normalized the argument.
        Parameters
        ----------
        data: Dict
            The input dict of arguments.
        strict: bool
            Strictly check the arguments.
        Returns
        -------
        data: Dict
            The normalized arguments.
        '''
        ta = cls.args()
        base = dargs.Argument("base", dict, ta)
        data = base.normalize_value(data, trim_pattern="_*")
        base.check_value(data, strict=strict)
        return data

    @OP.exec_sign_check
    def execute(
        self,
        ip: OPIO,
    ) -> OPIO:
        r'''Execute the OP.
        Parameters
        ----------
        ip : dict
            Input dict with components:
            - `task_name`: (`str`) The name of task.
            - `task_path`: (`Artifact(Path)`) The path that contains all input files prepareed by `PrepFp`.
            - `backward_list`: (`List[str]`) The output files the users need.
            - `log_name`: (`str`) The name of log file.
            - `backward_dir_name`: (`str`) The name of the directory which contains the backward files.
            - `config`: (`dict`) The config of FP task. May have `config['run']`, which defines the runtime configuration of the FP task.
            - `optional_artifact` : (`Artifact(Dict[str,Path])`) Other files that users or developers need.
            - `optional_input` : (`dict`) Other parameters the developers or users may need.
        Returns
        -------
            Output dict with components:
            - `backward_dir`: (`Artifact(Path)`) The directory which contains the files users need.
        Exceptions
        ----------
        TransientError
            On the failure of FP execution.
        FatalError
            When mandatory files are not found.
        '''
        backward_dir_name = ip["backward_dir_name"] 
        log_name = ip["log_name"] 
        backward_list = ip["backward_list"]
        run_config = ip["config"]["run"] if ip["config"]["run"] is not None else {}
        run_config = type(self).normalize_config(run_config, strict=False)
        optional_input = ip["optional_input"]
        task_name = ip["task_name"]
        task_path = ip["task_path"]
        input_files = self.input_files()
        input_files = [(Path(task_path) / ii).resolve() for ii in input_files]
        work_dir = Path(task_name)
        opt_input_files = []
        for ss,vv in ip["optional_artifact"].items():
            opt_input_files.append(ss)
        opt_input_files = [(Path(task_path) / ii).resolve() for ii in opt_input_files]

        with set_directory(work_dir):
            # link input files
            for ii in input_files:
                if not os.path.isfile(ii):
                    raise FatalError(f"cannot file file {ii}")
                iname = ii.name
                Path(iname).symlink_to(ii)
            for ii in opt_input_files:
                if os.path.isfile(ii):
                    iname = ii.name
                    Path(iname).symlink_to(ii)
            backward_dir_name = self.run_task(backward_dir_name,log_name,backward_list,run_config,optional_input)

        return OPIO(
            {
                "backward_dir": work_dir / backward_dir_name
            }
        )
