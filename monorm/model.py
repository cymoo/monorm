from collections import OrderedDict
from datetime import datetime
from typing import get_type_hints, Any, MutableMapping, Type, Union, Callable, List, Generator

from bson.json_util import dumps
from bson.objectid import ObjectId

from .fields import *
from .utils import *

__all__ = [
    'BaseModel',
    'EmbeddedModel'
]

hint_field_map = {
    str: StringField,
    int: IntField,
    float: FloatField,
    bool: BooleanField,
    bytes: BytesField,
    dict: DictField,
    list: ListField,
    datetime: DateTimeField,
    ObjectId: ObjectIdField,
    Any: AnyField,
}


def _hint_to_field(hint_type: Union[Type, Any]) -> Field:
    if hint_type in hint_field_map:
        return hint_field_map[hint_type]()
    if isclass(hint_type) and issubclass(hint_type, EmbeddedModel):
        return EmbeddedField(hint_type)
    # In Python 3.6 it's `typing.List` while 'list' in 3.7
    if hint_type.__dict__.get('__origin__') in (list, List):
        # noinspection PyUnresolvedReferences
        arg = hint_type.__args__[0]
        if str(arg) == '~T':
            return ListField()
        else:
            return ArrayField(_hint_to_field(arg))
    raise TypeError('cannot convert {!r} to a field'.format(hint_type))


class ModelType(type):
    def __new__(mcs, name, bases, attrs):
        if '_no_parse_hints' in attrs:
            return super().__new__(mcs, name, bases, attrs)

        # track the field definition order
        field_order = []

        for key, value in attrs.items():
            if isinstance(value, Field):
                if value.name is None:
                    value.name = key
                field_order.append(key)

        attrs['_field_order'] = field_order

        return super().__new__(mcs, name, bases, attrs)

    def _parse_type_hints(cls) -> None:
        annotations = cls.__dict__.get('__annotations__')
        if annotations is None:
            return

        types = get_type_hints(cls)
        field_order = cls.__dict__['_field_order']

        if len(field_order) != 0:
            warn('You are mixing type-hint-style with django-orm-style in {!r}; '
                 'the field definition order may not be reserved.'.format(cls))

        for name, hint in types.items():
            # filter out type hints of parent classes
            if name not in annotations:
                continue

            field = _hint_to_field(hint)
            field.name = name
            field_order.append(name)

            if cls.__dict__.get(name) is not None:
                field.default = getattr(cls, name)

            setattr(cls, name, field)

    def _process_meta(cls) -> None:
        fields = {key: value for key, value in cls.__dict__.items() if isinstance(value, Field)}
        meta = cls.__dict__.get('Meta')
        aliases = getattr(meta, 'aliases', [])
        required = getattr(meta, 'required', [])
        converters = getattr(meta, 'converters', {})
        validators = getattr(meta, 'validators', {})

        def ensure_field_exist(name):
            if name not in fields:
                raise ValueError('{!r} is not defined in {!r}.'.format(name, cls))

        if isinstance(aliases, dict):
            aliases = [(key, value) for key, value in aliases.items()]

        for field_name, alias in aliases:
            ensure_field_exist(field_name)
            fields[field_name].name = alias

        for field_name in required:
            ensure_field_exist(field_name)
            fields[field_name].required = True

        for field_name, converter in converters.items():
            ensure_field_exist(field_name)
            fields[field_name].converter = converter

        for field_name, validator in validators.items():
            ensure_field_exist(field_name)
            fields[field_name].validator = validator

    def __init__(cls, name, bases, attrs):
        if '_no_parse_hints' not in cls.__dict__:
            cls._parse_type_hints()
            cls._process_meta()

        super().__init__(name, bases, attrs)

    @classmethod
    def __prepare__(mcs, name, bases) -> MutableMapping:
        # class attribute definition order is preserved from python 3.6,
        # but cls.__dict__ will be updated by `setattr` in :meth:`~ModelType._parse_type_hints`;
        # to avoid bugs or dependencies on implementation details, here we return an `OrderedDict`.
        # https://www.python.org/dev/peps/pep-0520/
        return OrderedDict()


class BaseModel(metaclass=ModelType):
    """Base class of all model classes"""

    # The underlying data of models are saved in a dict-like object.
    # You can change it to `collections.OrderedDict`, `bson.son.SON` or other compatible types.
    dict_class: Type[MutableMapping] = dict

    # `json.dumps` cannot dump some values of bson object (objectId, datetime, etc.);
    # you can also use your own dump-function.
    json_dumps_func: Callable = dumps

    # Whether checks extra data that aren't declared in the model and emits some warnings.
    warn_extra_data: bool = True

    _no_parse_hints: bool = True
    __no_type_check__: bool = False

    def __init__(self,
                 bypass_conversion: bool = False,
                 bypass_validation: bool = False,
                 **kw):
        self._data = self.clean(kw, bypass_conversion, bypass_validation)

    # noinspection PyCallByClass
    def to_json(self, *arg, **kw) -> str:
        return type(self).json_dumps_func(self.to_dict(), *arg, **kw)

    def to_dict(self) -> MutableMapping:
        return self._data

    @classmethod
    def clean(cls,
              data: MutableMapping,
              bypass_conversion: bool = False,
              bypass_validation: bool = False) -> MutableMapping:
        root = EmbeddedField().init_root(cls)
        if not bypass_conversion:
            data = root.convert(data)
        if not bypass_validation:
            root.validate(data)
        return data

    @classmethod
    def from_data_unchanged(cls, data: MutableMapping):
        obj = cls(bypass_conversion=True, bypass_validation=True)
        obj._data = data
        return obj

    def __iter__(self):
        return self._iter_model()

    def _iter_model(self) -> Generator:
        for key in self._data.keys():
            yield getattr(self, key)


class EmbeddedModel(BaseModel):
    """Base class of user-defined embedded model"""
    _no_parse_hints: bool = True