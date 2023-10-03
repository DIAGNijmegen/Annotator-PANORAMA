import importlib
import json
from dataclasses import dataclass, field, InitVar, is_dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path

from strictyaml import load as yaml_load, YAML

from reconai import version


@dataclass
class Parameters:
    @dataclass
    class Data:
        """Parameters related to the dataset

        :param split_regex: first capture group is how to split mhas into cases (eg. '.*_(.*)_')
        :param filter_regex: result _is_ loaded
        :param shape_x: image columns to crop or zero-fill to
        :param shape_y: image rows to crop or zero-fill to
        :param sequence_length: length of T
        :param sequence_seed: seed for sequence generator
        :param normalize: image normalize divisor
        :param undersampling: how many k-lines to synthetically remove
        :param seed: seed to Gaussian random k-space masks
        """
        batch_size: int = 10
        shape_x: int = 256
        shape_y: int = 256
        sequence_length: int = 5
        sequence_seed: int = 11
        normalize: float = 1961.06
        undersampling: int = 8
        seed: int = 11

    @dataclass
    class Model:
        """Parameters related to the model

        :param iterations: CRNN iterations
        :param filters: CRNN filter count
        :param kernelsize: CRNN kernel convolution size
        :param channels: CRNN channel width
        :param layers: CRNN total layers
        :param bcrnn: whether to include the BCRNN layer (False, to replace with regular CRNN layer)
        """
        iterations: int = 5
        filters: int = 64
        kernelsize: int = 3
        channels: int = 1
        layers: int = 5
        bcrnn: bool = True

    @dataclass
    class Train:
        """Parameters related to the model

        :param epochs: number of epochs
        :param folds: number of folds
        :param lr: learning rate
        :param lr_gamma: learning rate decay per epoch
        :param lr_decay_end: set lr_gamma to 1 after n epochs. -1 for never.
        """
        @dataclass
        class Loss:
            """Parameters related to the Loss function

            :param mse: mean squared error
            :param ssim: structural similarity index measure
            :param dice: Dice segmentation coefficient
            """
            mse: float = 0
            ssim: float = 1
            dice: float = 0

            def __post_init__(self):
                total = sum(self.__dict__.values())
                for key in self.__dict__.keys():
                    setattr(self, key, getattr(self, key) / total)

        epochs: int = 5
        folds: int = 3
        loss: Loss = field(default_factory=Loss)
        lr: float = 0.001
        lr_gamma: float = 0.95
        lr_decay_end: int = 3

    @dataclass
    class Meta:
        name: str = 'untitled'
        date: str = 'date'
        in_dir: str = 'in_dir'
        out_dir: str = 'out_dir'
        debug: bool = False
        version: str = '0.0.0'

    data: Data = field(init=False, default_factory=Data)
    model: Model = field(init=False, default_factory=Model)
    train: Train = field(init=False, default_factory=Train)
    meta: Meta = field(init=False, default_factory=Meta)

    def __post_init__(self):
        self._yaml = None

    def _load_yaml(self, yaml: str):
        self._yaml = yaml_load(yaml)
        __deep_update__(self, self._yaml)

    def mkoutdir(self):
        raise NotImplementedError()

    @property
    def in_dir(self) -> Path:
        return Path(self.meta.in_dir)

    @property
    def out_dir(self) -> Path:
        return Path(self.meta.out_dir)

    def as_dict(self):
        return __deep_dict__(self)

    def __str__(self):
        return YAML(self.as_dict()).lines()


@dataclass
class TrainParameters(Parameters):
    in_dir_: InitVar[Path] = None
    out_dir_: InitVar[Path] = None
    yaml_file: InitVar[Path | str] = None

    def __post_init__(self, in_dir_: Path, out_dir_: Path, yaml_file: Path | str):
        super().__post_init__()

        debug = False
        if isinstance(yaml_file, str):
            yaml = yaml_file
        elif not yaml_file:
            yaml = importlib.resources.read_text('reconai.resources', 'config_debug.yaml')
            debug = True
        else:
            with open(yaml_file, 'r') as f:
                yaml = f.read()
        self._load_yaml(yaml)

        args = [
            datetime.now().strftime("%Y%m%dT%H%M"),
            'CRNN-MRI' + '' if self.model.bcrnn else 'b',
            f'R{self.data.undersampling}',
            f'E{self.train.epochs}',
            'DEBUG' if debug else None
        ]

        self.meta.name = '_'.join(a for a in args if a)
        self.meta.date = args[0]
        self.meta.in_dir = Path(in_dir_).as_posix()
        self.meta.out_dir = (Path(out_dir_) / self.meta.name).as_posix()
        self.meta.debug = debug
        self.meta.version = version

    def mkoutdir(self):
        self.out_dir.mkdir(exist_ok=False, parents=True)
        with open(self.out_dir / 'config.yaml', 'w') as f:
            f.write(str(self))


@dataclass
class TestParameters(Parameters):
    in_dir_: InitVar[Path] = None
    model_dir: InitVar[Path] = None
    model_name: InitVar[str] = None

    def __post_init__(self, in_dir_: Path, model_dir: Path, model_name: str):
        super().__post_init__()

        if model_name:
            model = (model_dir / model_name).with_suffix('.npz')
            if model.exists():
                self._model = model
            else:
                raise FileNotFoundError(f'no model named {model_name}')
        else:
            losses: dict[Path, float] = {}
            for file in model_dir.iterdir():
                if file.suffix == '.json':
                    with open(file, 'r') as f:
                        stats = json.load(f)
                        losses[file] = stats['loss_validate'][1]
            if not losses:
                raise FileNotFoundError(f'no models found in {model_dir}')
            self._model = min(losses, key=lambda k: losses[k])

        with open(model_dir / 'config.yaml', 'r') as f:
            yaml = f.read()
        self._load_yaml(yaml)

        self.meta.in_dir = Path(in_dir_).as_posix()
        self.meta.out_dir = (model_dir / f'test_{self._model.stem}').as_posix()

    def mkoutdir(self):
        self.out_dir.mkdir()

    @property
    def npz(self) -> Path:
        """
        Trained model (npz file)
        """
        return self._model.with_suffix('.npz')


types = (int, float, bool, str)


def __deep_dict__(obj) -> dict:
    r = {key: value for key, value in obj.__dict__.items() if not key.startswith('_')}
    for key in r.keys():
        if is_dataclass(r[key]):
            r[key] = __deep_dict__(r[key])
    return r


def __deep_update__(obj, yaml: YAML):
    for key, value in yaml.items():
        key = key.value
        if value.is_mapping():
            __deep_update__(getattr(obj, key), value)
        else:
            ty = type(getattr(obj, key))
            for t in types:
                if ty == t:
                    setattr(obj, key, t(value.value))
                    break
