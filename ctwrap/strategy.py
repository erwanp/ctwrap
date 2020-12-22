"""The :py:mod:`strategy` module defines :class:`Strategy` and derived objects
that specify strategies used in batch job simulations.

Batch job strategies are defined using YAML syntax in a ``ctwrap`` YAML
configuration file. The ``strategy`` block defines simulation strategies, where
valid entries contain lower case versions of valid :class:`Strategy` objects (e.g.
:class:`Sequence`, :class:`Matrix`). within each batch job strategy, parameters
to be varied are identified by key/value pairs.

Usage
+++++

An example for different options to define a parameter variation of a single
parameter ``foo``, - a :class:`Sequence`, - is given as:

.. code-block:: YAML

   strategy:
     sequence-1: # array of numeric values
       foo: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
     sequence-2: # values generated by numpy.linspace
       foo: { mode: linspace , limits: [0.1, 0.3], npoints: 3 }
     sequence-3: # values generated by numpy.arange
       bar: { mode: arange, limits: [2, -1], step: -1 }

:class:`Strategy` objects are generated automatically by ``ctwrap``
when a :class:`SimulationHandler` object is instantiated.

Class Definitions
+++++++++++++++++
"""

import warnings
from copy import deepcopy
from typing import Dict, Any, List, Optional
import numpy as np
import re
import warnings

from .parser import _parse, _write, Parser


def _replace_entry(nested, key_list, value):
    """Locate and replace entry in nested dictionary (recursive)

    Arguments:
       nested: Multi-level (nested) dictionary
       key_list: Sequence of keys leading to entry of interest
       value: Entry to replace
    """
    if key_list[0] not in nested:
        return nested

    sub = nested[key_list[0]]
    if len(key_list) == 1:
        if isinstance(sub, list):
            sub[0] = value
        elif isinstance(sub, str):
            _, unit = _parse(sub)
            sub = _write(value, unit)
        else:
            sub = value
    else:
        sub = _replace_entry(sub, key_list[1:], value)
    nested[key_list[0]] = sub
    return nested


def _task_list(tasks, prefix=None):
    """Create list of tasks (recursive)

    Arguments:
       tasks: Dictionary of variations
    """
    key = list(tasks.keys())[0]
    next = tasks.copy()
    values = next.pop(key)

    out = []
    for value in values:
        new = '{}_{}'.format(key, value)
        if prefix:
            new = '{}_{}'.format(prefix, new)
        if next:
            out.extend(_task_list(next, new))
        else:
            out.append(new)

    return out


def _sweep_matrix(tasks, defaults):
    """Replace entries along multiple axes (recursive)

    Arguments:
       defaults: Default parameters
       tasks: Dictionary of variations
    """
    key = list(tasks.keys())[0]
    next = tasks.copy()
    values = next.pop(key)
    entry = key.split('.')

    out = []
    for value in values:
        new = _replace_entry(deepcopy(defaults), entry, value)
        if next:
            out.extend(_sweep_matrix(next, new))
        else:
            out.append(new)

    return out


def _parse_mode(strat_dict):
    """
    parse the strategy values based on the mode specified (recursive)

    Argument:
        strat_dict(dict): variation values specification

    Output:
        out (dict): parsed variation values
    """

    keys = list(strat_dict.keys())
    next = strat_dict.copy()

    out = {}

    for key in keys:
        strat_val = next.pop(key)
        strat_limits = strat_val['limits']
        strat_max = strat_limits[1]
        strat_min = strat_limits[0]

        if "mode" not in strat_val:
            msg = "The required field 'mode' (strategy specification mode) is missing"
            raise KeyError(msg)

        if strat_val['mode'] == "linspace":
            strat_npoints = strat_val.get('npoints')
            if strat_npoints is None:
                msg = "The field 'npoints' (number of points) is missing"
                raise KeyError(msg)
            value = np.linspace(strat_min, strat_max, strat_npoints)
        elif strat_val['mode'] == "arange":
            if 'step' not in strat_val:
                msg = "The required field 'step' (step size) is missing"
                raise KeyError(msg)
            strat_step = strat_val['step']
            value = np.arange(strat_min, strat_max, strat_step)
        else:
            msg = "Unknown strategy mode '{}'".format(strat_val['mode'])
            raise KeyError(msg)

        # eliminate values affected by machine precision
        if all(value.astype(int) == value):
            value = re.findall(r'\d+', repr(value))
            out[key] = [int(v) for v in value]
        else:
            value = re.findall(r'[-+]?\d*\.\d*', repr(value))
            out[key] = [float(v) for v in value]

        if next:
            out.update(_parse_mode(next))

    return out


class Strategy:
    """Base class for batch simulation strategies

    The base class :class:`Strategy` defines methods common to all derived objects.
    While base objects are not viable strategies themselves, the factory loader
    :meth:`Strategy.load` can be used to load derived objects.

    As an example, a :class:`Sequence` object is created from a dictionary
    *strategy_dict* that contains a strategy specification *sequence-1*:

    .. code-block:: Python

        # create a 'Sequence' object specified by 'sequence-1'
        seq = ctwrap.Strategy.load(strategy_dict, 'sequence-1')
    """

    def __init__(self, value={}, name=None):
        self._check_input(value, 0)
        warnings.warn("Base clase does not implement batch simulation strategy")

    @property
    def info(self):
        return "Simulation strategy (base class)"

    @staticmethod
    def _check_input(value: Dict[str, Any], min_length: int, exact: Optional[bool]=True):
        """Check validity of input"""
        if not isinstance(value, dict):
            raise TypeError("Strategy needs to be defined by a dictionary")
        if exact and len(value) != min_length:
            raise ValueError("Invalid length: dictionary requires exactly "
                             "{} entry/entries.".format(min_length))
        elif len(value) < min_length:
            raise ValueError("Invalid length: dictionary requires at least "
                             "{} entry/entries.".format(min_length))
        return True

    @classmethod
    def load(cls, strategy, name=None):
        """Factory loader for strategy objects

        **Example:** The following code creates a `Sequence` object *strategy* that varies
        the variable *foobar*. The dictionary key at the top level has to contain a
        lower-case string corresponding to a strategy class:

        .. code-block:: Python

           strategy = ctwrap.Strategy.load({sequence_test: {'foobar': [0, 1, 2, 3]}})

        Arguments:
           strategy: Dictionary of batch job strategies, where lower-case keys
              specify the batch simulation strategy and the value holds parameters.
              Except for the case, the key needs to match the name of a `Strategy` object.
           name: Name of strategy (can be `None` if there is only one strategy)

        Returns:
           Instantiated `Strategy` object
        """
        if name:
            key = name
            value = strategy[name]
        elif len(strategy) == 1:
            key, value = list(strategy.items())[0]
            name = key
        else:
            raise ValueError("Parameter 'name' is required if multiple strategies are defined")

        if isinstance(value, dict) and any(isinstance(i, dict) for i in value.values()):
            value = _parse_mode(value)

        hooks = {'strategy': cls}
        for sub in cls.__subclasses__():
            hooks[sub.__name__.lower()] = sub

        cls_hook = None
        for sub, hook in hooks.items():
            if sub in key:
                cls_hook = hook
                break

        if cls_hook is None:
            raise NotImplementedError("Unknown strategy '{}'".format(key))

        return type(cls_hook.__name__, (cls_hook, ), {})(value, name=name)

    @property
    def definition(self):
        """Definition of batch simulation strategy"""
        raise NotImplementedError("Needs to be implemented by derived classes")

    @property
    def tasks(self):
        """List of tasks to be performed"""
        raise NotImplementedError("Needs to be implemented by derived classes")

    def configurations(self, defaults):
        """List of configurations to be tested"""
        raise NotImplementedError("Needs to be implemented by derived classes")

    def create_tasks(self, defaults: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create list of parameter sets for a parameter variation

        **Example:** The following code applies a parameter variation to the
        `Sequence` object *strategy* based on a parameter set *defaults*:

        .. code-block:: Python

           # define parameter variation
           foo = {'foobar': [0, 1, 2, 3]}
           strategy = ctwrap.Sequence(foo)

           # generate list of tasks based on default parameters
           defaults = {'foobar': 1, 'spam': 2.0, 'eggs': 3.14}
           tasks = strategy.create_tasks(defaults)

        Arguments:
           defaults: Dictionary containing default parameters

        Returns:
           List of dictionaries with parameter variation
        """
        return dict(zip(self.tasks, self.configurations(defaults)))


class Sequence(Strategy):
    """Variation of a single parameter

    .. code-block:: YAML

       sequence: # example for a batch sequence
         foo: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]

    Arguments:
       sweep: Dictionary specifying single parameter sequence
       name: Name of batch job strategy
    """

    def __init__(self, sweep: Dict[str, Any], name: Optional[str]=None):
        self._check_input(sweep, 1)
        self.sweep = sweep
        if name is None:
            name = type(self).__name__.lower()
        self.name = name

    @property
    def info(self):
        entry, values = list(self.sweep.items())[0]
        return 'Simulations for entry `{}` with values: {}'.format(entry, values)

    @classmethod
    def from_legacy(cls, items):
        """Create Sequence from ctwrap 0.1.0 syntax"""
        return cls({items['entry']: items['values']})

    @property
    def definition(self):
        ""
        return self.sweep

    @property
    def tasks(self):
        ""
        return _task_list(self.sweep)

    def configurations(self, defaults):
        ""
        return _sweep_matrix(self.sweep, defaults)


class Matrix(Strategy):
    """Variation of multiple parameters

    .. code-block:: YAML

       matrix: # example for a batch matrix
         foo: [0.1, 0.2, 0.3]
         bar: [2, 1, 0]

    Arguments:
       matrix: Dictionary specifying multiple parameter sequences
       name: Name of batch job strategy
    """

    def __init__(self, matrix: Dict[str, Any], name: Optional[str]=None):
        self._check_input(matrix, 2, False)
        self.matrix = matrix
        if name is None:
            name = type(self).__name__.lower()
        self.name = name

    @property
    def info(self):
        entries = ['{}'.format(k) for k in self.matrix.keys()]
        return 'Simulations for entries {}'.format(entries)

    @property
    def definition(self):
        ""
        return self.matrix

    @property
    def tasks(self):
        ""
        return _task_list(self.matrix)

    def configurations(self, defaults):
        ""
        return _sweep_matrix(self.matrix, defaults)


class Sobol(Strategy):
    """Pseudo-randomly sampled parameter space via Sobol sequence

    Not implemented; there is prior work in Ayoobi and Schoegl, PROCI 2015
    """
    # Note: old work is Python 2 / Cantera 2.1

    def __init__(self, ranges):
        self._check_input(ranges, 1, False)
        self.ranges = ranges

    # def create_tasks(self):
    #     raise NotImplementedError("tbd")
