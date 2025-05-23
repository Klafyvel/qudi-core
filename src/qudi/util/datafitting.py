# -*- coding: utf-8 -*-

"""
ToDo: Document

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-core/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

__all__ = ('is_fit_model', 'get_all_fit_models', 'FitConfiguration', 'FitConfigurationsModel',
           'FitContainer')

import importlib
import logging
import inspect
import lmfit
import numpy as np
from PySide2 import QtCore
from typing import Iterable, Optional, Mapping, Union

import qudi.util.fit_models as _fit_models_ns
from qudi.util.mutex import Mutex
from qudi.util.units import create_formatted_output
from qudi.util.helpers import iter_modules_recursive
from qudi.util.fit_models.model import FitModelBase


_log = logging.getLogger(__name__)


def is_fit_model(cls):
    return inspect.isclass(cls) and issubclass(cls, FitModelBase) and (cls is not FitModelBase)


# Upon import of this module the global attribute _fit_models is initialized with a dict
# containing all importable fit model objects with names as keys.
_fit_models = dict()
for mod_finder in iter_modules_recursive(_fit_models_ns.__path__, _fit_models_ns.__name__ + '.'):
    try:
        _fit_models.update(
            {name: cls for name, cls in
             inspect.getmembers(importlib.import_module(mod_finder.name), is_fit_model)}
        )
    except:
        _log.exception(
            f'Exception while importing qudi.util.fit_models sub-module "{mod_finder.name}":'
        )


def get_all_fit_models():
    return _fit_models.copy()


class FitConfiguration:
    """
    """

    def __init__(self, name: str, model: str, estimator: Optional[str] = None, custom_parameters: Optional[lmfit.Parameters] = None):
        assert isinstance(name, str), 'FitConfiguration name must be str type.'
        assert name, 'FitConfiguration name must be non-empty string.'
        assert model in _fit_models, f'Invalid fit model name encountered: "{model}".'
        assert name != 'No Fit', '"No Fit" is a reserved name for fit configs. Choose another.'

        self._name = name
        self._model = model
        self._estimator = None
        self._custom_parameters = None
        self.estimator = estimator
        self.custom_parameters = custom_parameters

    @property
    def name(self):
        return self._name

    @property
    def model(self):
        return self._model

    @property
    def estimator(self):
        return self._estimator

    @estimator.setter
    def estimator(self, value: Union[str, None]):
        if value is not None:
            assert value in self.available_estimators, \
                f'Invalid fit model estimator encountered: "{value}"'
        self._estimator = value

    @property
    def available_estimators(self):
        return tuple(_fit_models[self._model]().estimators)

    @property
    def default_parameters(self):
        params = _fit_models[self._model]().make_params()
        return lmfit.Parameters() if params is None else params

    @property
    def custom_parameters(self):
        return self._custom_parameters.copy() if self._custom_parameters is not None else None

    @custom_parameters.setter
    def custom_parameters(self, value: Union[lmfit.Parameters, None]):
        if value is not None:
            default_params = self.default_parameters
            invalid = set(value).difference(default_params)
            assert not invalid, f'Invalid model parameters encountered: {invalid}'
            assert isinstance(value, lmfit.Parameters), \
                'Property custom_parameters must be of type <lmfit.Parameters>.'
        self._custom_parameters = value.copy() if value is not None else None

    def to_dict(self):
        return {
            'name': self._name,
            'model': self._model,
            'estimator': self._estimator,
            'custom_parameters': None if self._custom_parameters is None else self._custom_parameters.dumps()
        }

    @classmethod
    def from_dict(cls, dict_repr):
        assert set(dict_repr) == {'name', 'model', 'estimator', 'custom_parameters'}
        if isinstance(dict_repr['custom_parameters'], str):
            dict_repr['custom_parameters'] = lmfit.Parameters().loads(
                dict_repr['custom_parameters']
            )
        return cls(**dict_repr)


class FitConfigurationsModel(QtCore.QAbstractListModel):
    """
    """

    sigFitConfigurationsChanged = QtCore.Signal(tuple)

    def __init__(self, *args, configurations=None, **kwargs):
        assert (configurations is None) or all(isinstance(c, FitConfiguration) for c in configurations)
        super().__init__(*args, **kwargs)
        self._fit_configurations = list() if configurations is None else list(configurations)

    @property
    def model_names(self):
        return tuple(_fit_models)

    @property
    def model_estimators(self):
        return {name: tuple(model().estimators) for name, model in _fit_models.items()}

    @property
    def model_default_parameters(self):
        return {name: model().make_params() for name, model in _fit_models.items()}

    @property
    def configuration_names(self):
        return tuple(fc.name for fc in self._fit_configurations)

    @property
    def configurations(self):
        return self._fit_configurations.copy()

    @QtCore.Slot(str, str)
    def add_configuration(self, name: str, model: str, estimator: Optional[str] = None, custom_parameters: Optional[lmfit.Parameters] = None):
        assert name not in self.configuration_names, f'Fit config "{name}" already defined.'
        assert name != 'No Fit', '"No Fit" is a reserved name for fit configs. Choose another.'
        config = FitConfiguration(name, model, estimator, custom_parameters)
        new_row = len(self._fit_configurations)
        self.beginInsertRows(self.createIndex(new_row, 0), new_row, new_row)
        self._fit_configurations.append(config)
        self.endInsertRows()
        self.sigFitConfigurationsChanged.emit(self.configuration_names)

    @QtCore.Slot(str)
    def remove_configuration(self, name):
        try:
            row_index = self.configuration_names.index(name)
        except ValueError:
            return
        self.beginRemoveRows(self.createIndex(row_index, 0), row_index, row_index)
        self._fit_configurations.pop(row_index)
        self.endRemoveRows()
        self.sigFitConfigurationsChanged.emit(self.configuration_names)

    def get_configuration_by_name(self, name):
        try:
            row_index = self.configuration_names.index(name)
        except ValueError:
            raise ValueError(f'No fit configuration found with name "{name}".')
        return self._fit_configurations[row_index]

    def flags(self, index):
        if index.isValid():
            return QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsEnabled

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._fit_configurations)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole:
            if (orientation == QtCore.Qt.Horizontal) and (section == 0):
                return 'Fit Configurations'
            elif orientation == QtCore.Qt.Vertical:
                try:
                    return self.configuration_names[section]
                except IndexError:
                    pass
        return None

    def data(self, index=QtCore.QModelIndex(), role=QtCore.Qt.DisplayRole):
        if (role == QtCore.Qt.DisplayRole) and (index.isValid()):
            try:
                return self._fit_configurations[index.row()]
            except IndexError:
                pass
        return None

    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if index.isValid():
            config = index.data(QtCore.Qt.DisplayRole)
            if config is None:
                return False
            new_params = value[1]
            params = config.default_parameters
            for name in [p for p in params if p not in new_params]:
                del params[name]
            for name, p in params.items():
                value_tuple = new_params[name]
                p.set(vary=value_tuple[0],
                      value=value_tuple[1],
                      min=value_tuple[2],
                      max=value_tuple[3])
            config.estimator = None if not value[0] else value[0]
            config.custom_parameters = None if not params else params
            self.dataChanged.emit(self.createIndex(index.row(), 0),
                                  self.createIndex(index.row(), 0))
            return True
        return False

    def dump_configs(self):
        """
        Returns all currently held fit configurations as dictionary representations containing only
        data types that can be dumped as YAML in the Qudi app status.

        Returns
        -------
        list of dict
            List of fit configuration dictionary representations.
        """
        return [cfg.to_dict() for cfg in self._fit_configurations]

    def load_configs(self, configs):
        """Initializes/overwrites all currently held fit configurations by a given iterable of dict
        representations (see also: FitConfigurationsModel.dump_configs).

        This method will reset the list model.

        Parameters
        ----------
        configs : iterable
            Iterable of FitConfiguration dictionary representations.
            See also: FitConfigurationsModel.dump_configs.

        """
        config_objects = list()
        for cfg in configs:
            try:
                config_objects.append(FitConfiguration.from_dict(cfg))
            except:
                _log.warning(f'Unable to load fit configuration:\n{cfg}')
        self.beginResetModel()
        self._fit_configurations = config_objects
        self.endResetModel()
        self.sigFitConfigurationsChanged.emit(self.configuration_names)


class FitContainer(QtCore.QObject):
    """
    """
    sigFitConfigurationsChanged = QtCore.Signal(tuple)  # config_names
    sigLastFitResultChanged = QtCore.Signal(str, object)  # (fit_config name, lmfit.ModelResult)

    def __init__(self, *args, config_model, **kwargs):
        assert isinstance(config_model, FitConfigurationsModel)
        super().__init__(*args, **kwargs)
        self._access_lock = Mutex()
        self._configuration_model = config_model
        self._last_fit_result = None
        self._last_fit_config = 'No Fit'

        self._configuration_model.sigFitConfigurationsChanged.connect(
            self.sigFitConfigurationsChanged
        )

    @property
    def fit_configurations(self):
        return self._configuration_model.configurations

    @property
    def fit_configuration_names(self):
        return self._configuration_model.configuration_names

    @property
    def last_fit(self):
        with self._access_lock:
            return self._last_fit_config, self._last_fit_result

    @QtCore.Slot(str, object, object)
    def fit_data(self, fit_config, x, data):
        with self._access_lock:
            if fit_config:
                # Handle "No Fit" case
                if fit_config == 'No Fit':
                    self._last_fit_result = None
                    self._last_fit_config = 'No Fit'
                else:
                    config = self._configuration_model.get_configuration_by_name(fit_config)
                    model = _fit_models[config.model]()
                    estimator = config.estimator
                    add_parameters = config.custom_parameters
                    if estimator is None:
                        parameters = model.make_params()
                    else:
                        parameters = model.estimators[estimator](data, x)
                    if add_parameters is not None:
                        for name, param in add_parameters.items():
                            parameters[name] = param
                    result = model.fit(data, parameters, x=x)
                    # Mutate lmfit.ModelResult object to include high-resolution result curve
                    high_res_x = np.linspace(x[0], x[-1], len(x) * 10)
                    result.high_res_best_fit = (high_res_x,
                                                model.eval(**result.best_values, x=high_res_x))
                    self._last_fit_result = result
                    self._last_fit_config = fit_config
                self.sigLastFitResultChanged.emit(self._last_fit_config, self._last_fit_result)
                return self._last_fit_config, self._last_fit_result
            return '', None

    @staticmethod
    def formatted_result(fit_result: Union[None, lmfit.model.ModelResult],
                         parameters_units: Optional[Mapping[str, str]] = None) -> str:
        if fit_result is None:
            return ''
        if parameters_units is None:
            parameters_units = dict()

        parameters_to_format = dict()
        for name, param in fit_result.params.items():
            stderr = param.stderr if param.vary else None
            stderr = np.nan if param.vary and stderr is None else stderr

            parameters_to_format[name] = {'value': param.value,
                                          'error': stderr,
                                          'unit': parameters_units.get(name, '')}

        return create_formatted_output(parameters_to_format)

    @staticmethod
    def dict_result(fit_result: Union[None, lmfit.model.ModelResult],
                    parameters_units: Optional[Mapping[str, str]] = None,
                    export_keys: Optional[Iterable[str]] = ('value', 'stderr')) -> dict:
        if fit_result is None:
            return dict()
        if parameters_units is None:
            parameters_units = dict()

        fitparams = fit_result.result.params
        export_dict = {'model': fit_result.model.name}

        for key, res in fitparams.items():
            dict_i = {key: getattr(res, key) for key in export_keys}
            dict_i['unit'] = parameters_units.get(key, '')
            export_dict[key] = dict_i

        return export_dict
