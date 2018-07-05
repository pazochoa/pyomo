"""Flexibility analysis."""

from __future__ import division

import textwrap

from pyomo.core.base.constraint import Constraint
from pyomo.core.expr.numvalue import value
from pyomo.core.plugins.transform.hierarchy import IsomorphicTransformation
from pyomo.common.plugin import alias
from pyomo.repn import generate_standard_repn


class RenameMe(IsomorphicTransformation):
    """Change constraints to be a bound on the variable.

    Look, documentation.
    """

    alias('contrib.flex_test',
          doc=textwrap.fill(textwrap.dedent(__doc__.strip())))

    def _apply_to(self, model, uncertain_list=[]):
        """Apply the transformation to the given model."""
        print("Hi")
        do_flex_analysis(model, uncertain_list)


def do_flex_analysis(model, uncertain_list):
    raise NotImplementedError()
