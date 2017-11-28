#  ___________________________________________________________________________
#
#  Pyomo: Python Optimization Modeling Objects
#  Copyright 2017 National Technology and Engineering Solutions of Sandia, LLC
#  Under the terms of Contract DE-NA0003525 with National Technology and 
#  Engineering Solutions of Sandia, LLC, the U.S. Government retains certain 
#  rights in this software.
#  This software is distributed under the 3-clause BSD License.
#  ___________________________________________________________________________

from __future__ import division

#
# These symbols are part of pyomo.core.expr
#
__public__ = ['linear_expression', 'nonlinear_expression']
#
# These symbols are part of pyomo.core.expr.current
#
__all__ = (
'linear_expression',
'nonlinear_expression',
'mutable_sum_context',
'mutable_linear_context',
'decompose_term',
'clone_counter',
'clone_counter_context',
'clone_expression',
'evaluate_expression',
'identify_components',
'identify_variables',
'generate_sum_expression',
'generate_mul_expression',
'generate_other_expression',
'generate_intrinsic_function_expression',
'generate_relational_expression',
'chainedInequalityErrorMessage',
'ExpressionBase',
'EqualityExpression',
'InequalityExpression',
'ProductExpression',
'PowExpression',
'ExternalFunctionExpression',
'NPV_ExternalFunctionExpression',
'GetItemExpression',
'Expr_if',
'LinearExpression',
'ReciprocalExpression',
'NegationExpression',
'ViewSumExpression',
'UnaryFunctionExpression',
'AbsExpression',
'compress_expression',
'NPV_NegationExpression',
'NPV_ExternalFunctionExpression',
'NPV_PowExpression',
'NPV_ProductExpression',
'NPV_ReciprocalExpression',
'NPV_SumExpression',
'NPV_UnaryFunctionExpression',
'NPV_AbsExpression',
'SimpleExpressionVisitor',
'ExpressionValueVisitor',
'ExpressionReplacementVisitor',
'pyomo5_variable_types',
'_SumExpression',               # This should not be referenced, except perhaps while testing code
'_MutableViewSumExpression',    # This should not be referenced, except perhaps while testing code
'_MutableLinearExpression',     # This should not be referenced, except perhaps while testing code
)

import math
import logging
import sys
import traceback
from copy import deepcopy
from collections import deque
from itertools import islice
from six import StringIO, next, string_types, itervalues
from six.moves import xrange, builtins
from weakref import ref

logger = logging.getLogger('pyomo.core')

from pyutilib.misc.visitor import SimpleVisitor, ValueVisitor
from pyutilib.math.util import isclose

from pyomo.core.expr.numvalue import \
    (NumericValue,
     NumericConstant,
     native_types,
     native_numeric_types,
     as_numeric,
     value)
from pyomo.core.expr.expr_common import \
    (_add, _sub, _mul, _div,
     _pow, _neg, _abs, _inplace,
     _unary, _radd, _rsub, _rmul,
     _rdiv, _rpow, _iadd, _isub,
     _imul, _idiv, _ipow, _lt, _le,
     _eq) 
from pyomo.core.expr import expr_common as common


def chainedInequalityErrorMessage(msg=None):
    if msg is None:
        msg = "Relational expression used in an unexpected Boolean context."
    buf = StringIO()
    InequalityExpression.chainedInequality.to_string(buf)
    # We are about to raise an exception, so it's OK to reset chainedInequality
    info = InequalityExpression.call_info
    InequalityExpression.chainedInequality = None
    InequalityExpression.call_info = None

    args = ( str(msg).strip(), buf.getvalue().strip(), info[0], info[1],
             ':\n    %s' % info[3] if info[3] is not None else '.' )
    return """%s

The inequality expression:
    %s
contains non-constant terms (variables) that were evaluated in an
unexpected Boolean context at
  File '%s', line %s%s

Evaluating Pyomo variables in a Boolean context, e.g.
    if expression <= 5:
is generally invalid.  If you want to obtain the Boolean value of the
expression based on the current variable values, explicitly evaluate the
expression using the value() function:
    if value(expression) <= 5:
or
    if value(expression <= 5):
""" % args


_ParamData = None
SimpleParam = None
TemplateExpressionError = None
def initialize_expression_data():
    """
    A function used to initialize expression global data.

    This function is necessary to avoid global imports.  It is executed
    when ``pyomo.environ`` is imported.
    """
    global pyomo5_variable_types
    from pyomo.core.base import _VarData, _GeneralVarData, SimpleVar
    from pyomo.core.kernel.component_variable import IVariable, variable
    pyomo5_variable_types.update([_VarData, _GeneralVarData, IVariable, variable, SimpleVar])
    _MutableLinearExpression.vtypes = pyomo5_variable_types
    #
    global _ParamData
    global SimpleParam
    global TemplateExpressionError
    from pyomo.core.base.param import _ParamData, SimpleParam
    from pyomo.core.base.template_expr import TemplateExpressionError
    #
    global pyomo5_named_expression_types
    from pyomo.core.base.expression import _GeneralExpressionData, SimpleExpression
    from pyomo.core.base.objective import _GeneralObjectiveData, SimpleObjective
    pyomo5_expression_types.update([_GeneralExpressionData, SimpleExpression, _GeneralObjectiveData, SimpleObjective])
    pyomo5_named_expression_types.update([_GeneralExpressionData, SimpleExpression, _GeneralObjectiveData, SimpleObjective])
    #
    # [functionality] chainedInequality allows us to generate symbolic
    # expressions of the type "a < b < c".  This provides a buffer to hold
    # the first inequality so the second inequality can access it later.
    #
    InequalityExpression.chainedInequality = None
    InequalityExpression.call_info = None



def compress_expression(expr):
    """
    Deprecated function that was used to compress deep Pyomo5
    expression trees.
    """
    return expr


class clone_counter_context(object):
    """ Context manager for counting cloning events.

    This context manager counts the number of times that the
    :func:`clone_expression <pyomo.core.expr.current.clone_expression>`
    function is executed.
    """

    _count = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    @property
    def count(self):
        """A property that returns the clone count value.
        """
        return clone_counter_context._count

#: A clone counter context manager object that simplifies the
#: use of this context manager.  Specifically, different 
#: instances of this context manger are not necessary.
clone_counter = clone_counter_context()


class mutable_sum_context(object):
    """ Context manager for mutable sums.

    This context manager is used to compute a sum while
    treating the summation as a mutable object.
    """

    def __enter__(self):
        self.e = _MutableViewSumExpression([])
        return self.e

    def __exit__(self, *args):
        pass
        if self.e.__class__ == _MutableViewSumExpression:
            self.e.__class__ = ViewSumExpression

#: A context manager object for nonlinear expressions.
#: This is an instance of the :class:`mutable_sum_contex <pyomo.core.expr.current.mutable_sum_context>` context manager.
#: Different instances of this context manger are not necessary.
nonlinear_expression = mutable_sum_context()


class mutable_linear_context(object):
    """ Context manager for mutable linear sums.

    This context manager is used to compute a linear sum while
    treating the summation as a mutable object.
    """

    def __enter__(self):
        """
        The :class:`_MutableLinearExpression <pyomo.core.expr.current._MutableLinearExpression>`
        class is the context that is used to to
        hold the mutable linear sum.
        """
        self.e = _MutableLinearExpression()
        return self.e

    def __exit__(self, *args):
        """
        The context is changed to the 
        :class:`LinearExpression <pyomo.core.expr.current.LinearExpression>`
        class to transform the context into a nonmutable
        form.
        """
        if self.e.__class__ == _MutableLinearExpression:
            self.e.__class__ = LinearExpression

#: A context manager object for linear expressions.
#: This is an instance of the :class:`mutable_linear_contex <pyomo.core.expr.current.mutable_lienar_context>` context manager.
#: Different instances of this context manger are not necessary.
linear_expression = mutable_linear_context()


#-------------------------------------------------------
#
# Visitor Logic
#
#-------------------------------------------------------

class SimpleExpressionVisitor(object):
    """
    Note:
        This class is a customization of the PyUtilib :class:`SimpleVisitor
        <pyutilib.misc.visitor.SimpleVisitor>` class that is tailored
        to efficiently walk Pyomo expression trees.  However, this class
        is not a subclass of the PyUtilib :class:`SimpleVisitor
        <pyutilib.misc.visitor.SimpleVisitor>` class because all key methods
        are reimplemented.
    """

    def visit(self, node):  #pragma: no cover
        """
        Visit a node in an expression tree and perform some operation on
        it.

        This method should be over-written by a user
        that is creating a sub-class.

        Args:
            node: a node in an expression tree

        Returns:
            nothing
        """
        pass

    def finalize(self):     #pragma: no cover
        """
        Return the "final value" of the search.

        The default implementation returns :const:`None`, because
        the traditional visitor pattern does not return a value.

        Returns:
            The final value after the search.  Default is :const:`None`.
        """
        pass

    def xbfs(self, node):
        """
        Breadth-first search of an expression tree, 
        except that leaf nodes are immediately visited.

        Note:
            This method has the same functionality as the 
            PyUtilib :class:`SimpleVisitor.xbfs <pyutilib.misc.visitor.SimpleVisitor.xbfs>`
            method.  The difference is that this method
            is tailored to efficiently walk Pyomo expression trees.

        Args:
            node: The root node of the expression tree that is searched.

        Returns:
            The return value is determined by the :func:`finalize` function,
            which may be defined by the user.  Defaults to :const:`None`.
        """
        dq = deque([node])
        while dq:
            current = dq.popleft()
            self.visit(current)
            #for c in self.children(current):
            for c in current.args:
                #if self.is_leaf(c):
                if c.__class__ in native_numeric_types or not c.is_expression() or c.nargs() == 0:
                    self.visit(c)
                else:
                    dq.append(c)
        return self.finalize()

    def xbfs_yield_leaves(self, node):
        """
        Breadth-first search of an expression tree, except that 
        leaf nodes are immediately visited.

        Note:
            This method has the same functionality as the 
            PyUtilib :class:`SimpleVisitor.xbfs_yield_leaves <pyutilib.misc.visitor.SimpleVisitor.xbfs_yield_leaves>`
            method.  The difference is that this method
            is tailored to efficiently walk Pyomo expression trees.

        Args:
            node: The root node of the expression tree
                that is searched.

        Returns:
            The return value is determined by the :func:`finalize` function,
            which may be defined by the user.  Defaults to :const:`None`.
        """
        #
        # If we start with a leaf, then yield it and stop iteration
        #
        if not node.__class__ in pyomo5_expression_types or node.nargs() == 0:
            ans = self.visit(node)
            if not ans is None:
                yield ans
            raise StopIteration
        #
        # Iterate through the tree.
        #
        dq = deque([node])
        while dq:
            current = dq.popleft()
            #self.visit(current)
            #for c in self.children(current):
            for c in current.args:
                #if self.is_leaf(c):
                if c.__class__ in pyomo5_expression_types and c.nargs() > 0:
                    dq.append(c)
                else:
                    ans = self.visit(c)
                    if not ans is None:
                        yield ans


class ExpressionValueVisitor(object):
    """
    Note:
        This class is a customization of the PyUtilib :class:`ValueVisitor
        <pyutilib.misc.visitor.ValueVisitor>` class that is tailored
        to efficiently walk Pyomo expression trees.  However, this class
        is not a subclass of the PyUtilib :class:`ValueVisitor
        <pyutilib.misc.visitor.ValueVisitor>` class because all key methods
        are reimplemented.
    """

    def visit(self, node, values):  #pragma: no cover
        """
        Visit a node in a tree and compute its value using
        the values of its children.

        This method should be over-written by a user
        that is creating a sub-class.

        Args:
            node: a node in a tree
            values: a list of values of this node's children

        Returns:
            The *value* for this node, which is computed using :attr:`values`
        """
        pass

    def visiting_potential_leaf(self, node):
        """ 
        Visit a node and return its value if it is a leaf.

        Note:
            This method needs to be over-written for a specific
            visitor application.

        Args:
            node: a node in a tree

        Returns:
            A tuple: ``(flag, value)``.   If ``flag`` is False,
            then the node is not a leaf and ``value`` is :const:`None`.  
            Otherwise, ``value`` is the computed value for this node.
        """
        raise RuntimeError("The visiting_potential_leaf method needs to be defined.")

    def finalize(self, ans):    #pragma: no cover
        """
        This method defines the return value for the search methods
        in this class.

        The default implementation returns the value of the
        initial node (aka the root node), because
        this visitor pattern computes and returns value for each
        node to enable the computation of this value.

        Args:
            ans: The final value computed by the search method.

        Returns:
	        The final value after the search. Defaults to simply
	        returning :attr:`ans`.
        """
        return ans

    def dfs_postorder_stack(self, node):
        """
        Perform a depth-first search in postorder using a stack
        implementation.

        Note:
            This method has the same functionality as the 
            PyUtilib :class:`ValueVisitor.dfs_postorder_stack <pyutilib.misc.visitor.ValueVisitor.dfs_postorder_stack>`
            method.  The difference is that this method
            is tailored to efficiently walk Pyomo expression trees.

        Args:
            node: The root node of the expression tree
                that is searched.

        Returns:
            The return value is determined by the :func:`finalize` function,
            which may be defined by the user.
        """
        flag, value = self.visiting_potential_leaf(node)
        if flag:
            return value
        #_stack = [ (node, self.children(node), 0, len(self.children(node)), [])]
        _stack = [ (node, node._args, 0, node.nargs(), [])]
        #
        # Iterate until the stack is empty
        #
        # Note: 1 is faster than True for Python 2.x
        #
        while 1:
            #
            # Get the top of the stack
            #   _obj        Current expression object
            #   _argList    The arguments for this expression objet
            #   _idx        The current argument being considered
            #   _len        The number of arguments
            #   _result     The return values
            #
            _obj, _argList, _idx, _len, _result = _stack.pop()
            #
            # Iterate through the arguments
            #
            while _idx < _len:
                _sub = _argList[_idx]
                _idx += 1
                flag, value = self.visiting_potential_leaf(_sub)
                if flag:
                    _result.append( value )
                else:
                    #
                    # Push an expression onto the stack
                    #
                    _stack.append( (_obj, _argList, _idx, _len, _result) )
                    _obj                    = _sub
                    #_argList                = self.children(_sub)
                    _argList                = _sub._args
                    _idx                    = 0
                    _len                    = _sub.nargs()
                    _result                 = []
            #
            # Process the current node
            #
            ans = self.visit(_obj, _result)
            if _stack:
                #
                # "return" the recursion by putting the return value on the end of the results stack
                #
                _stack[-1][-1].append( ans )
            else:
                return self.finalize(ans)


class ExpressionReplacementVisitor(object):
    """
    Note:
        This class is a customization of the PyUtilib :class:`ValueVisitor
        <pyutilib.misc.visitor.ValueVisitor>` class that is tailored
        to support replacement of sub-trees in a Pyomo expression
        tree.  However, this class is not a subclass of the PyUtilib
        :class:`ValueVisitor <pyutilib.misc.visitor.ValueVisitor>`
        class because all key methods are reimplemented.
    """

    def __init__(self, memo=None):
        """
        Contruct a visitor that is tailored to support the
        replacement of sub-trees in a pyomo expression tree.

        Args:
            memo (dict): A dictionary mapping object ids to 
                objects.  This dictionary has the same semantics as
                the memo object used with ``copy.deepcopy``.  Defaults
                to None, which indicates that no user-defined
                dictionary is used.
        """
        if memo is None:
            self.memo = {'__block_scope__': { id(None): False }}
        else:
            self.memo = memo

    def visit(self, node, values):
        """
        Visit and clone nodes that have been expanded.

        Note:
            This method normally does not need to be re-defined
            by a user.

        Args:
            node: The node that will be cloned.
            values (list): The list of child nodes that have been
                cloned.  These values are used to define the 
                cloned node.

        Returns:
            The cloned node.  Default is to simply return the node.
        """
        return node

    def visiting_potential_leaf(self, node):
        """ 
        Visit a node and return a cloned node if it is a leaf.

        Note:
            This method needs to be over-written for a specific
            visitor application.

        Args:
            node: a node in a tree

        Returns:
            A tuple: ``(flag, value)``.   If ``flag`` is False,
            then the node is not a leaf and ``value`` is :const:`None`.  
            Otherwise, ``value`` is a cloned node.
        """
        raise RuntimeError("The visiting_potential_leaf method needs to be defined.")

    def finalize(self, ans):
        """
        This method defines the return value for the search methods
        in this class.

        The default implementation returns the value of the
        initial node (aka the root node), because
        this visitor pattern computes and returns value for each
        node to enable the computation of this value.

        Args:
            ans: The final value computed by the search method.

        Returns:
	        The final value after the search. Defaults to simply
	        returning :attr:`ans`.
        """
        return ans

    def construct_node(self, node, values):
        """
        Call the expression construct_node() method.
        """
        return node.construct_node( tuple(values), self.memo )

    def dfs_postorder_stack(self, node):
        """
        Perform a depth-first search in postorder using a stack
        implementation.

        This method replaces subtrees.  This method detects if the
        :func:`visit` method returns a different object.  If so, then
        the node has been replaced and search process is adapted
        to replace all subsequent parent nodes in the tree.

        Note:
            This method has the same functionality as the 
            PyUtilib :class:`ValueVisitor.dfs_postorder_stack <pyutilib.misc.visitor.ValueVisitor.dfs_postorder_stack>`
            method that is tailored to support the
            replacement of sub-trees in a Pyomo expression tree.

        Args:
            node: The root node of the expression tree
                that is searched.

        Returns:
            The return value is determined by the :func:`finalize` function,
            which may be defined by the user.
        """
        flag, value = self.visiting_potential_leaf(node)
        if flag:
            return value
        #_stack = [ (node, self.children(node), 0, len(self.children(node)), [])]
        _stack = [ (node, node._args, 0, node.nargs(), [False])]
        #
        # Iterate until the stack is empty
        #
        # Note: 1 is faster than True for Python 2.x
        #
        while 1:
            #
            # Get the top of the stack
            #   _obj        Current expression object
            #   _argList    The arguments for this expression objet
            #   _idx        The current argument being considered
            #   _len        The number of arguments
            #   _result     The 'dirty' flag followed by return values
            #
            _obj, _argList, _idx, _len, _result = _stack.pop()
            #
            # Iterate through the arguments
            #
            while _idx < _len:
                _sub = _argList[_idx]
                _idx += 1
                flag, value = self.visiting_potential_leaf(_sub)
                if flag:
                    if id(value) != id(_sub):
                        _result[0] = True
                    _result.append( value )
                else:
                    #
                    # Push an expression onto the stack
                    #
                    _stack.append( (_obj, _argList, _idx, _len, _result) )
                    _obj                    = _sub
                    #_argList                = self.children(_sub)
                    _argList                = _sub._args
                    _idx                    = 0
                    _len                    = _sub.nargs()
                    _result                 = [False]
            #
            # Process the current node
            #
            # If the user has defined a visit() function in a
            # subclass, then call that function.  But if the user
            # hasn't created a new class and we need to, then
            # call the ExpressionReplacementVisitor.visit() function.
            #
            ans = self.visit(_obj, _result[1:])
            if _result[0] and id(ans) == id(_obj):
                ans = self.construct_node(_obj, _result[1:])
            if _stack:
                if _result[0]:
                    _stack[-1][-1][0] = True
                #
                # "return" the recursion by putting the return value on the end of the results stack
                #
                _stack[-1][-1].append( ans )
            else:
                return self.finalize(ans)



#-------------------------------------------------------
#
# Functions used to process expression trees
#
#-------------------------------------------------------

# =====================================================
#  clone_expression
# =====================================================

class _CloneVisitor(ExpressionValueVisitor):

    def __init__(self, clone_leaves=False, memo=None):
        self.clone_leaves = clone_leaves
        self.memo = memo

    def visit(self, node, values):
        """ Visit nodes that have been expanded """
        return node.construct_node( tuple(values), self.memo )

    def visiting_potential_leaf(self, node):
        """ 
        Visiting a potential leaf.

        Return True if the node is not expanded.
        """
        if node.__class__ in native_numeric_types:
            #
            # Store a native or numeric object
            #
            return True, deepcopy(node, self.memo)

        if node.__class__ not in pyomo5_expression_types:
            #
            # Store a kernel object that is cloned
            #
            if self.clone_leaves:
                return True, deepcopy(node, self.memo)
            else:
                return True, node

        if node.__class__ in pyomo5_named_expression_types:
            #
            # Do not clone named expressions unless we are cloning leaves
            #
            if self.clone_leaves:
                return True, deepcopy(node, self.memo)
            else:
                return True, node

        return False, None


def clone_expression(expr, memo=None, clone_leaves=True):
    """Function used to clone an expression.

    Cloning is roughly equivalent to calling ``copy.deepcopy``.
    However, the :attr:`clone_leaves` argument can be used to 
    clone only interior (i.e. non-leaf) nodes in the expresion
    tree.  Additionally, this function uses a non-recursive 
    logic, which makes it more scalable than the logic in 
    ``copy.deepcopy``.

    Args:
        expr: The expression that will be cloned.
        memo (dict): A dictionary mapping object ids to 
            objects.  This dictionary has the same semantics as
            the memo object used with ``copy.deepcopy``.  Defaults
            to None, which indicates that no user-defined
            dictionary is used.
        clone_leaves (bool): If True, then leaves are
            cloned along with the rest of the expression. 
            Defaults to :const:`True`.
   
    Returns: 
        The cloned expression.
    """
    clone_counter_context._count += 1
    if not memo:
        memo = {'__block_scope__': { id(None): False }}
    #
    visitor = _CloneVisitor(clone_leaves=clone_leaves, memo=memo)
    return visitor.dfs_postorder_stack(expr)


# =====================================================
#  _sizeof_expression
# =====================================================

class _SizeVisitor(SimpleExpressionVisitor):

    def __init__(self):
        self.counter = 0

    def visit(self, node):
        self.counter += 1

    def finalize(self):
        return self.counter


def _sizeof_expression(expr):
    """
    Return the number of nodes in the expression tree.

    Args:
        expr: The root node of an expression tree.

    Returns:
        A non-negative integer that is the number of 
        interior and leaf nodes in the expression tree.
    """
    visitor = _SizeVisitor()
    return visitor.xbfs(expr)
    
 
# =====================================================
#  evaluate_expression
# =====================================================

class _EvaluationVisitor(ExpressionValueVisitor):

    def visit(self, node, values):
        """ Visit nodes that have been expanded """
        return node._apply_operation(values)

    def visiting_potential_leaf(self, node):
        """ 
        Visiting a potential leaf.

        Return True if the node is not expanded.
        """
        if node.__class__ in native_numeric_types:
            return True, node

        if node.__class__ in pyomo5_variable_types:
            return True, value(node)

        if not node.is_expression():
            return True, value(node)

        return False, None


def evaluate_expression(exp, exception=True):
    """
    Evaluate the value of the expression.

    Args:
        expr: The root node of an expression tree.
        exception (bool): A flag that indicates whether 
            exceptions are raised.  If this flag is
            :const:`False`, then an exception that
            occurs while evaluating the expression 
            is caught and the return value is :const:`None`.
            Default is :const:`True`.

    Returns:
        A floating point value if the expression evaluates
        normally, or :const:`None` if an exception occurs
        and is caught.
    """
    try:
        visitor = _EvaluationVisitor()
        return visitor.dfs_postorder_stack(exp)

    except TemplateExpressionError:
        if exception:
            raise
        return None
    except ValueError:
        if exception:
            raise
        return None


# =====================================================
#  identify_variables
# =====================================================

class _VariableVisitor(SimpleExpressionVisitor):

    def __init__(self, types):
        self.seen = set()
        if types.__class__ is set:
            self.types = types
        else:
            self.types = set(types)
        
    def visit(self, node):
        if node.__class__ in self.types:
            if id(node) in self.seen:
                return
            self.seen.add(id(node))
            return node


def identify_components(expr, component_types):
    """
    A generator that yields a sequence of nodes
    in an expression tree that belong to a specified set.

    Args:
        expr: The root node of an expression tree.
        component_types (set or list): A set of class 
            types that will be matched during the search.

    Yields:
        Each node that is found.
    """
    #
    # OPTIONS:
    # component_types - set (or list) if class types to find
    # in the expression.
    #
    visitor = _VariableVisitor(component_types)
    for v in visitor.xbfs_yield_leaves(expr):
        yield v


def identify_variables(expr, include_fixed=True):
    """
    A generator that yields a sequence of variables 
    in an expression tree.

    Args:
        expr: The root node of an expression tree.
        include_fixed (bool): If :const:`True`, then
            this generator will yield variables whose
            value is fixed.  Defaults to :const:`True`.

    Yields:
        Each variable that is found.
    """
    #
    # OPTIONS:
    # include_fixed - list includes fixed variables
    #
    visitor = _VariableVisitor(pyomo5_variable_types)
    if include_fixed:
        for v in visitor.xbfs_yield_leaves(expr):
            yield v
    else:
        for v in visitor.xbfs_yield_leaves(expr):
            if not v.is_fixed():
                yield v


# =====================================================
#  _polynomial_degree
# =====================================================

class _PolyDegreeVisitor(ExpressionValueVisitor):

    def visit(self, node, values):
        """ Visit nodes that have been expanded """
        return node._polynomial_degree(values)

    def visiting_potential_leaf(self, node):
        """ 
        Visiting a potential leaf.

        Return True if the node is not expanded.
        """
        if node.__class__ in native_types or not node.is_potentially_variable():
            return True, 0

        if not node.is_expression():
            return True, 0 if node.is_fixed() else 1

        return False, None


def _polynomial_degree(node):
    """
    Return the polynomial degree of the expression.

    Args:
        node: The root node of an expression tree.

    Returns:
        A non-negative integer that is the polynomial
        degree if the expression is polynomial, or :const:`None` otherwise.
    """
    visitor = _PolyDegreeVisitor()
    return visitor.dfs_postorder_stack(node)


# =====================================================
#  _expression_is_fixed
# =====================================================

class _IsFixedVisitor(ExpressionValueVisitor):
    """
    NOTE: This doesn't check if combiner logic is 
    all or any and short-circuit the test.  It's
    not clear that that is an important optimization.
    """

    def visit(self, node, values):
        """ Visit nodes that have been expanded """
        return node._is_fixed(values)

    def visiting_potential_leaf(self, node):
        """ 
        Visiting a potential leaf.

        Return True if the node is not expanded.
        """
        if node.__class__ in native_numeric_types or not node.is_potentially_variable():
            return True, True

        elif not node.__class__ in pyomo5_expression_types:
            return True, node.is_fixed()

        return False, None


def _expression_is_fixed(node):
    """
    Return the polynomial degree of the expression.

    Args:
        node: The root node of an expression tree.

    Returns:
        A non-negative integer that is the polynomial
        degree if the expression is polynomial, or :const:`None` otherwise.
    """
    visitor = _IsFixedVisitor()
    return visitor.dfs_postorder_stack(node)


# =====================================================
#  _expression_to_string
# =====================================================

class _ToStringVisitor(ExpressionValueVisitor):

    def __init__(self, verbose, labeler):
        super(_ToStringVisitor, self).__init__()
        self.verbose = verbose
        self.labeler = labeler

    def visit(self, node, values):
        """ Visit nodes that have been expanded """
        tmp = []
        for i,val in enumerate(values):
            arg = node._args[i]
            if arg.__class__ in native_numeric_types:
                tmp.append(val)
            elif arg.__class__ in pyomo5_variable_types:
                tmp.append(val)
            elif arg is None:
                tmp.append('Undefined')
            elif not self.verbose and arg.is_expression() and node._precedence() < arg._precedence():
                tmp.append("({0})".format(val))
            else:
                tmp.append(val)
        return node._to_string(tmp, verbose=self.verbose)

    def visiting_potential_leaf(self, node):
        """ 
        Visiting a potential leaf.

        Return True if the node is not expanded.
        """
        if node is None:
            return True, 'Undefined'

        if node.__class__ in native_types:
            return True, str(node)

        if node.__class__ in pyomo5_variable_types:
            return True, node.to_string(verbose=self.verbose, labeler=self.labeler)

        if not node.is_expression():
            return True, node.to_string(verbose=self.verbose, labeler=self.labeler)

        return False, None


def _expression_to_string(expr, verbose=None, labeler=None):
    """
    Return the polynomial degree of the expression.

    Args:
        node: The root node of an expression tree.

    Returns:
        A non-negative integer that is the polynomial
        degree if the expression is polynomial, or :const:`None` otherwise.
    """
    verbose = common.TO_STRING_VERBOSE if verbose is None else verbose
    visitor = _ToStringVisitor(verbose, labeler)
    return visitor.dfs_postorder_stack(expr)


#-------------------------------------------------------
#
# Expression classes
#
#-------------------------------------------------------


class ExpressionBase(NumericValue):
    """
    An object that defines a mathematical expression that can be evaluated

    m.p = Param(default=10, mutable=False)
    m.q = Param(default=10, mutable=True)
    m.x = var()
    m.y = var(initialize=1)
    m.y.fixed = True

                            m.p     m.q     m.x     m.y
    constant                T       F       F       F
    potentially_variable    F       F       T       T
    npv                     T       T       F       F
    fixed                   T       T       F       T
    """

    __slots__ =  ('_args',)
    PRECEDENCE = 0

    def __init__(self, args):
        self._args = args

    def nargs(self):
        """
        Returns the number of child nodes.
        
        By default, Pyomo expressions represent binary operations
        with two arguments.
    
        Note:
            This function does not simply compute the length of
            :attr:`_args` because some expression classes use
            a subset of the :attr:`_args` array.  Thus, it
            is imperative that developers use this method!

        Returns:
            A nonnegative integer that is the number of child nodes.
        """
        return 2

    def arg(self, i):
        """
        Return the i-th child node.

        Args:
            i (int): Nonnegative index of the child that is returned.

        Returns:
            The i-th child node.
        """
        if i < 0 or i >= self.nargs():
            raise KeyError("Invalid index for expression argument: %d" % i)
        return self._args[i]

    @property
    def args(self):
        """
        A generator that yields the child nodes.

        Yields:
            Each child node in order.
        """
        return islice(self._args, self.nargs())

    def __getstate__(self):
        """
        Pickle the expression object

        Returns:
            The pickled state.
        """
        state = super(ExpressionBase, self).__getstate__()
        for i in ExpressionBase.__slots__:
           state[i] = getattr(self,i)
        return state

    def __nonzero__(self):      #pragma: no cover
        """
        Compute the value of the expression and convert it to
        a boolean.

        Returns:
            A boolean value.
        """
        return bool(self())

    __bool__ = __nonzero__

    def __call__(self, exception=True):
        """
        Evaluate the value of the expression tree.

        Args:
            exception (bool): If :const:`False`, then
                an exception raised while evaluating
                is captured, and the value returned is
                :const:`None`.  Default is :const:`True`.

        Returns:
            The value of the expression or :const:`None`.
        """
        return evaluate_expression(self, exception)

    def __str__(self):
        """
        Returns a string description of the expression.

        Note:
            The value of ``pyomo.core.expr.expr_common.TO_STRING_VERBOSE``
            is used to configure the execution of this method.
            If this value is :const:`True`, then the string
            representation is a nested function description of the expression.
            The default is :const:`False`, which is an algebraic
            description of the expression.

        Returns:
            A string.
        """
        from pyomo.repn import generate_standard_repn
        #if True:
        try:
            #
            # Try to factor the constant and linear terms when printing NONVERBOSE
            #
            if common.TO_STRING_VERBOSE:
                expr = self
            elif self.__class__ is InequalityExpression:
                expr = self
                # TODO: chained inequalities
                #if self._args[0].__class__ is InequalityExpression:
                #    repn0a = generate_standard_repn(self._args[0]._args[0], compress=False, quadratic=False, compute_values=False)
                #    repn0b = generate_standard_repn(self._args[0]._args[1], compress=False, quadratic=False, compute_values=False)
                #    lhs = InequalityExpression( (repn0a.to_expression(), repn0b.to_expression()), self._args[0]._strict, self._args[0]._cloned_from)
                #    repn1 = generate_standard_repn(self._args[1], compress=False, quadratic=False, compute_values=False)
                #    expr = InequalityExpression( (lhs, repn1.to_expression()), self._strict, self._cloned_from)
                #elif self._args[0].__class__ is InequalityExpression:
                #    repn0 = generate_standard_repn(self._args[0], compress=False, quadratic=False, compute_values=False)
                #    repn1a = generate_standard_repn(self._args[1]._args[0], compress=False, quadratic=False, compute_values=False)
                #    repn1b = generate_standard_repn(self._args[1]._args[1], compress=False, quadratic=False, compute_values=False)
                #    rhs = InequalityExpression( (repn1a.to_expression(), repn1b.to_expression()), self._args[1]._strict, self._args[1]._cloned_from)
                #    expr = InequalityExpression( (repn0.to_expression(), rhs), self._strict, self._cloned_from)
                #else:
                #    repn0 = generate_standard_repn(self._args[0], compress=False, quadratic=False, compute_values=False)
                #    repn1 = generate_standard_repn(self._args[1], compress=False, quadratic=False, compute_values=False)
                #    expr = InequalityExpression( (repn0.to_expression(), repn1.to_expression()), self._strict, self._cloned_from)
            elif self.__class__ is EqualityExpression:
                repn0 = generate_standard_repn(self._args[0], quadratic=False, compute_values=False)
                repn1 = generate_standard_repn(self._args[1], quadratic=False, compute_values=False)
                expr = EqualityExpression( (repn0.to_expression(), repn1.to_expression()) )
            else:
                repn = generate_standard_repn(self, quadratic=False, compute_values=False)
                expr = repn.to_expression()
        #else:
        except Exception as e:
            #print(str(e))
            #
            # Fall back to simply printing the expression in an
            # unfactored form.
            #
            expr = self
        #
        # Output the string
        #
        return _expression_to_string(expr)
        #buf = StringIO()
        #buf.write(expression_to_string(expr))
        #ans = buf.getvalue()
        #buf.close()
        #return ans

    def clone(self, substitute=None):
        """
        Return a clone of the expression tree.

        Note:
            This method does not clone the leaves of the tree,
            which are numeric constants and variables.  It only 
            clones the interior nodes, and expression leaf nodes
            like :class:`_MutableLinearExpression <pyomo.core.expr.current._MutableLinearExpression>`.
            
        Args:
            substitute (dict): a dictionary that maps object ids to clone
                objects generated earlier during the cloning process.

        Returns:
            A new expression tree.
        """
        return clone_expression(self, memo=substitute, clone_leaves=False)

    def __deepcopy__(self, memo):
        """
        Return a clone of the expression tree.

        Note:
            This method clones the leaves of the tree.
        Args:
            memo (dict): a dictionary that maps object ids to clone
                objects generated earlier during the cloning process.

        Returns:
            A new expression tree.
        """
        return clone_expression(self, memo=memo, clone_leaves=True)

    def construct_node(self, args, memo):
        """
        Construct a node using given arguments. 
   
        This class provides a consistent interface for constructing a
        node, which is used in tree visitor scripts.  In the simplest
        case, this simply returns::

            self.__class__(args))

        But in general this constructs a copy of the current
        expression object using local data as well as arguments
        that represent the child nodes.   Thus, this method can be viewed
        as a node-level clone method.

        Args:
            args (list): A list of child nodes for the new expression
                object
            memo (dict): A dictionary that maps object ids to clone
                objects generated earlier during a cloning process.

        Returns:
            A new expression object with the same type as the current
            class.
        """
        return self.__class__(args)

    def getname(self, *args, **kwds):                       #pragma: no cover
        """The text name of this Expression function"""
        raise NotImplementedError("Derived expression (%s) failed to "\
            "implement getname()" % ( str(self.__class__), ))

    def is_constant(self):
        """Return True if this expression is an atomic constant

        This method contrasts with the is_fixed() method.  This method
        returns True if the expression is an atomic constant, that is it
        is composed exclusively of constants and immutable parameters.
        NumericValue objects returning is_constant() == True may be
        simplified to their numeric value at any point without warning.

        Note:  This defaults to False, but gets redefined in sub-classes.
        """
        return False

    def is_fixed(self):
        """
        Return :const:`True` if this expression contains no free variables.

        Returns:
            A boolean.
        """
        return _expression_is_fixed(self)

    def _is_fixed(self, values):
        """
        Compute whether this expression is fixed given
        the fixed values of its children.

        This method is called by the :class:`_IsFixedVisitor
        <pyomo.core.expr.current._IsFixedVisitor>` class.  It can
        be over-written by expression classes to customize this
        logic.

        Args:
            values (list): A list of boolean values that indicate whether
                the children of this expression are fixed

        Returns:
            A boolean that is :const:`True` if the fixed values of the
            children are all :const:`True`.
        """
        return all(values)

    def is_potentially_variable(self):
        """
        Return :const:`True` if this expression contains variables.

        This method returns :const:`True` if there are any variables
        within this expression.  This method returns :const:`True`
        even if there the variables in the expression are currently
        fixed.

        Returns:
            A boolean.  Defaults to :const:`True` for expressions.
        """
        return True

    def is_expression(self):
        """
        Return :const:`True` if this object is an expression.

        This method obviously returns :const:`True` for this class, but it
        is included in other classes within Pyomo that are not expressions,
        which allows for a check for expressions without
        evaluating the class type.

        Returns:
            A boolean.
        """
        return True

    def size(self):
        """
        Return the number of nodes in the expression tree.

        Returns:
            A nonnegative integer that is the number of interior and leaf
            nodes in the expression tree.
        """
        return _sizeof_expression(self)

    def polynomial_degree(self):
        """
        Return the polynomial degree of the expression.

        Returns:
            A nonnegative integer that is the polynomial degree of
            the expression, if the expression is polynomial.  And
            :const:`None` otherwise.
        """
        return _polynomial_degree(self)

    def _polynomial_degree(self, values):                          #pragma: no cover
        """
        Compute the polynomial degree of this expression given
        the degree values of its children.

        This method is called by the :class:`_PolyDegreeVisitor
        <pyomo.core.expr.current._PolyDegreeVisitor>` class.  It can
        be over-written by expression classes to customize this
        logic.

        Args:
            values (list): A list of values that indicate the degree
                of the children expression.

        Returns:
            A nonnegative integer that is the polynomial degree of the
            expression, or :const:`None`.  Default is :const:`None`.
        """
        return None

    def to_string(self, verbose=False, labeler=None):
        return _expression_to_string(self, verbose=verbose, labeler=labeler)

    def _precedence(self):
        return ExpressionBase.PRECEDENCE


class NegationExpression(ExpressionBase):
    __slots__ = ()

    PRECEDENCE = 4

    def nargs(self):
        return 1

    def getname(self, *args, **kwds):
        return 'neg'

    def _polynomial_degree(self, result):
        return result[0]

    def _precedence(self):
        return NegationExpression.PRECEDENCE

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1})".format(self.getname(), values[0])
        tmp = values[0]
        if tmp[0] == '-':
            i = 1
            while tmp[i] == ' ':
                i += 1
            return tmp[i:]
        return "- "+tmp

    def _apply_operation(self, result):
        return -result[0]


class NPV_NegationExpression(NegationExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


class ExternalFunctionExpression(ExpressionBase):
    __slots__ = ('_fcn',)

    def __init__(self, args, fcn=None):
        """Construct a call to an external function"""
        self._args = args
        self._fcn = fcn

    def nargs(self):
        return len(self._args)

    def construct_node(self, args, memo):
        return self.__class__(args, self._fcn)

    def __getstate__(self):
        result = super(ExternalFunctionExpression, self).__getstate__()
        for i in ExternalFunctionExpression.__slots__:
            result[i] = getattr(self, i)
        return result

    def getname(self, *args, **kwds):           #pragma: no cover
        return self._fcn.getname(*args, **kwds)

    def _polynomial_degree(self, result):
        if result[0] is 0:
            return 0
        else:
            return None

    def _apply_operation(self, result):
        """Evaluate the expression"""
        return self._fcn.evaluate( result )     #pragma: no cover

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1}, {2})".format(self.getname(), values[0], values[1])
        tmp = [self._fcn.getname(), '(']
        if len(values) > 0:
            if type(self._args[0]) in string_types:
                tmp.append("'{0}'".format(values[0]))
            else:
                tmp.append(values[0])
        for i in range(1, len(values)):
            tmp.append(', ')
            if type(self._args[i]) in string_types:
                tmp.append("'{0}'".format(values[i]))
            else:
                tmp.append(values[i])
        tmp.append(')')
        return "".join(tmp)


class NPV_ExternalFunctionExpression(ExternalFunctionExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


class PowExpression(ExpressionBase):

    __slots__ = ()
    PRECEDENCE = 2

    def _polynomial_degree(self, result):
        # PowExpression is a tricky thing.  In general, a**b is
        # nonpolynomial, however, if b == 0, it is a constant
        # expression, and if a is polynomial and b is a positive
        # integer, it is also polynomial.  While we would like to just
        # call this a non-polynomial expression, these exceptions occur
        # too frequently (and in particular, a**2)
        l,r = result
        if isclose(r, 0):
            if isclose(l, 0):
                return 0
            try:
                # NOTE: use value before int() so that we don't
                #       run into the disabled __int__ method on
                #       NumericValue
                exp = value(self._args[1])
                if exp == int(exp):
                    if l is not None and exp > 0:
                        return l * exp
                    elif exp == 0:
                        return 0
            except:
                pass
        return None

    def _is_fixed(self, args):
        assert(len(args) == 2)
        if not args[1]:
            return False
        return args[0] or isclose(value(self._args[1]), 0)

    def _precedence(self):
        return PowExpression.PRECEDENCE

    def _apply_operation(self, result):
        _l, _r = result
        return _l ** _r

    def getname(self, *args, **kwds):
        return 'pow'

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1}, {2})".format(self.getname(), values[0], values[1])
        return "{0}**{1}".format(values[0], values[1])


class NPV_PowExpression(PowExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


class _LinearOperatorExpression(ExpressionBase):
    """An 'abstract' class that defines the polynomial degree for a simple
    linear operator
    """

    __slots__ = ()

    def _polynomial_degree(self, result):
        # NB: We can't use max() here because None (non-polynomial)
        # overrides a numeric value (and max() just ignores it)
        ans = 0
        for x in result:
            if x is None:
                return None
            elif ans < x:
                ans = x
        return ans


class InequalityExpression(_LinearOperatorExpression):
    """An object that defines a series of less-than or
    less-than-or-equal expressions"""

    __slots__ = ('_strict', '_cloned_from')
    PRECEDENCE = 9

    # Used to process chained inequalities
    chainedInequality = None
    call_info = None

    def __init__(self, args, strict, cloned_from):
        """Constructor"""
        super(InequalityExpression,self).__init__(args)
        self._strict = strict
        self._cloned_from = cloned_from

    def nargs(self):
        return len(self._args)

    def construct_node(self, args, memo):
        return self.__class__(args, self._strict, self._cloned_from)

    def __getstate__(self):
        result = super(InequalityExpression, self).__getstate__()
        for i in InequalityExpression.__slots__:
            result[i] = getattr(self, i)
        return result

    def __nonzero__(self):
        if InequalityExpression.chainedInequality is not None:     #pragma: no cover
            raise TypeError(chainedInequalityErrorMessage())
        if not self.is_constant() and len(self._args) == 2:
            InequalityExpression.call_info = traceback.extract_stack(limit=2)[-2]
            InequalityExpression.chainedInequality = self
            #return bool(self())                - This is needed to apply simple evaluation of inequalities
            return True

        return bool(self())

    __bool__ = __nonzero__

    def is_relational(self):
        return True

    def _precedence(self):
        return InequalityExpression.PRECEDENCE

    def _apply_operation(self, result):
        for i, a in enumerate(result):
            if not i:
                pass
            elif self._strict[i-1]:
                if not _l < a:
                    return False
            else:
                if not _l <= a:
                    return False
            _l = a
        return True

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1}, {2})".format(self.getname(), values[0], values[1])
        if len(values) == 2:
            return "{0}  {1}  {2}".format(values[0], '<' if self._strict[0] else '<=', values[1])
        return "{0}  {1}  {2}  {3}  {4}".format(values[0], '<' if self._strict[0] else '<=', values[1], '<' if self._strict[1] else '<=', values[2])
        
    def is_constant(self):
        return self._args[0].is_constant() and self._args[1].is_constant()

    def is_potentially_variable(self):
        return self._args[0].is_potentially_variable() or self._args[1].is_potentially_variable()


class EqualityExpression(_LinearOperatorExpression):
    """An object that defines a equal-to expression"""

    __slots__ = ()
    PRECEDENCE = 9

    def nargs(self):
        return len(self._args)

    def __nonzero__(self):
        if InequalityExpression.chainedInequality is not None:         #pragma: no cover
            raise TypeError(chainedInequalityErrorMessage())
        return bool(self())

    __bool__ = __nonzero__

    def is_relational(self):
        return True

    def _precedence(self):
        return EqualityExpression.PRECEDENCE

    def _apply_operation(self, result):
        _l, _r = result
        return _l == _r

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1}, {2})".format(self.getname(), values[0], values[1])
        return "{0}  ==  {1}".format(values[0], values[1])
        
    def is_constant(self):
        return self._args[0].is_constant() and self._args[1].is_constant()

    def is_potentially_variable(self):
        return self._args[0].is_potentially_variable() or self._args[1].is_potentially_variable()


class ProductExpression(ExpressionBase):
    """An object that defines a product expression"""

    __slots__ = ()
    PRECEDENCE = 4

    def _precedence(self):
        return ProductExpression.PRECEDENCE

    def _polynomial_degree(self, result):
        # NB: We can't use sum() here because None (non-polynomial)
        # overrides a numeric value (and sum() just ignores it - or
        # errors in py3k)
        a, b = result
        if a is None or b is None:
            return None
        else:
            return a + b

    def getname(self, *args, **kwds):
        return 'prod'

    def _inline_operator(self):
        return '*'

    def _apply_operation(self, result):
        _l, _r = result
        return _l * _r

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1}, {2})".format(self.getname(), values[0], values[1])
        return "{0}*{1}".format(values[0],values[1])


class NPV_ProductExpression(ProductExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


class ReciprocalExpression(ExpressionBase):
    """An object that defines a division expression"""

    __slots__ = ()
    PRECEDENCE = 3.5

    def nargs(self):
        return 1

    def _precedence(self):
        return ReciprocalExpression.PRECEDENCE

    def _polynomial_degree(self, result):
        if result[0] is 0:
            return 0
        return None

    def getname(self, *args, **kwds):
        return 'recip'

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1})".format(self.getname(), values[0])
        return "(1/{0})".format(values[0])

    def _apply_operation(self, result):
        return 1 / result[0]


class NPV_ReciprocalExpression(ReciprocalExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


class _SumExpression(_LinearOperatorExpression):
    """An object that defines a simple summation of expressions"""

    __slots__ = ()
    PRECEDENCE = 6

    def _precedence(self):
        return _SumExpression.PRECEDENCE

    def _apply_operation(self, result):
        l_, r_ = result
        return l_ + r_


class NPV_SumExpression(_SumExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


class ViewSumExpression(_SumExpression):
    """An object that defines a summation with 1 or more terms using a shared list."""

    __slots__ = ('_nargs','_shared_args')
    PRECEDENCE = 6

    def __init__(self, args):
        self._args = args
        self._shared_args = False
        self._nargs = len(self._args)

    def add(self, new_arg):
        if new_arg.__class__ in native_numeric_types and isclose(new_arg,0):
            return self
        # Clone 'self', because ViewSumExpression are immutable
        self._shared_args = True
        self = self.__class__(self._args)
        #
        if new_arg.__class__ is ViewSumExpression or new_arg.__class__ is _MutableViewSumExpression:
            self._args.extend( islice(new_arg._args, new_arg._nargs) )
        elif not new_arg is None:
            self._args.append(new_arg)
        self._nargs = len(self._args)
        return self

    def nargs(self):
        return self._nargs

    def _precedence(self):
        return ViewSumExpression.PRECEDENCE

    def _apply_operation(self, result):
        return sum(result)

    def construct_node(self, args, memo):
        return self.__class__(list(args))

    def __getstate__(self):
        result = super(ViewSumExpression, self).__getstate__()
        for i in ViewSumExpression.__slots__:
            result[i] = getattr(self, i)
        return result

    def getname(self, *args, **kwds):
        return 'viewsum'

    def is_constant(self):
        return False
        #
        # In most normal contexts, a ViewSumExpression is non-constant.  When
        # Forming expressions, constant parameters are turned into numbers, which
        # are simply added.  Mutable parameters, variables and expressions are 
        # not constant.
        #
        #for v in islice(self._args, self._nargs):
        #    if not (v.__class__ in native_numeric_types or v.is_constant()):
        #        return False
        #return True

    def is_potentially_variable(self):
        for v in islice(self._args, self._nargs):
            if v.__class__ in pyomo5_variable_types:
                return True
            if not v.__class__ in native_numeric_types and v.is_potentially_variable():
                return True
        return False

    def _to_string(self, values, verbose=False):
        if verbose:
            tmp = [values[0]]
            for i in range(1,len(values)):
                tmp.append(", ")
                tmp.append(values[i])
            return "{0}({1})".format(self.getname(), "".join(tmp))

        tmp = [values[0]]
        for i in range(1,len(values)):
            if values[i][0] == '-':
                tmp.append(' - ')
                j = 1
                while values[i][j] == ' ':
                    j += 1
                tmp.append(values[i][j:])
            else:
                tmp.append(' + ')
                tmp.append(values[i])
        return ''.join(tmp)


class _MutableViewSumExpression(ViewSumExpression):

    __slots__ = ()

    def add(self, new_arg):
        if new_arg.__class__ in native_numeric_types and isclose(new_arg,0):
            return self
        # Do not clone 'self', because _MutableViewSumExpression are mutable
        #self._shared_args = True
        #self = self.__class__(list(self.args))
        #
        if new_arg.__class__ is ViewSumExpression or new_arg.__class__ is _MutableViewSumExpression:
            self._args.extend( islice(new_arg._args, new_arg._nargs) )
        elif not new_arg is None:
            self._args.append(new_arg)
        self._nargs = len(self._args)
        return self


class GetItemExpression(ExpressionBase):
    """Expression to call "__getitem__" on the base"""

    __slots__ = ('_base',)
    PRECEDENCE = 1

    def _precedence(self):
        return GetItemExpression.PRECEDENCE

    def __init__(self, args, base=None):
        """Construct an expression with an operation and a set of arguments"""
        self._args = args
        self._base = base

    def nargs(self):
        return len(self._args)

    def construct_node(self, args, memo):
        return self.__class__(args, self._base)

    def __getstate__(self):
        result = super(GetItemExpression, self).__getstate__()
        for i in GetItemExpression.__slots__:
            result[i] = getattr(self, i)
        return result

    def getname(self, *args, **kwds):
        return self._base.getname(*args, **kwds)

    def is_potentially_variable(self):
        if any(arg.is_potentially_variable() for arg in self._args if not arg.__class__ in native_types):
            for x in itervalues(self._base):
                if not x.__class__ in native_types and x.is_potentially_variable():
                    return True
        return False
        
    def is_fixed(self):
        if any(self._args):
            for x in itervalues(self._base):
                if not x.__class__ in native_types and not x.is_fixed():
                    return False
        return True
        
    def _polynomial_degree(self, result):
        if any(x != 0 for x in result):
            return None
        ans = 0
        for x in itervalues(self._base):
            if x.__class__ in native_types:
                continue
            tmp = x.polynomial_degree()
            if tmp is None:
                return None
            elif tmp > ans:
                ans = tmp
        return ans

    def _apply_operation(self, result):
        return value(self._base.__getitem__( tuple(result) ))

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1}, {2})".format(self.getname(), values[0], values[1])
        return "%s%s" % (self.getname(), values[0])

    def resolve_template(self):
        return self._base.__getitem__(tuple(value(i) for i in self._args))


class Expr_if(ExpressionBase):
    """An object that defines a dynamic if-then-else expression"""

    __slots__ = ('_if','_then','_else')

    # **NOTE**: This class evaluates the branching "_if" expression
    #           on a number of occasions. It is important that
    #           one uses __call__ for value() and NOT bool().

    def __init__(self, IF_=None, THEN_=None, ELSE_=None):
        """Constructor"""
        
        if type(IF_) is tuple and THEN_==None and ELSE_==None:
            IF_, THEN_, ELSE_ = IF_
        self._args = (IF_, THEN_, ELSE_)
        self._if = IF_
        self._then = THEN_
        self._else = ELSE_
        if self._if.__class__ in native_types:
            self._if = as_numeric(self._if)

    def nargs(self):
        return 3

    def __getstate__(self):
        state = super(Expr_if, self).__getstate__()
        for i in Expr_if.__slots__:
            state[i] = getattr(self, i)
        return state

    def getname(self, *args, **kwds):
        return "Expr_if"

    def _is_fixed(self, args):
        assert(len(args) == 3)
        if args[0]: #self._if.is_constant():
            if self._if():
                return args[1] #self._then.is_constant()
            else:
                return args[2] #self._else.is_constant()
        else:
            return False

    def is_constant(self):
        if self._if.__class__ in native_numeric_types or self._if.is_constant():
            if value(self._if):
                return (self._then.__class__ in native_numeric_types or self._then.is_constant())
            else:
                return (self._else.__class__ in native_numeric_types or self._else.is_constant())
        else:
            return (self._then.__class__ in native_numeric_types or self._then.is_constant()) and (self._else.__class__ in native_numeric_types or self._else.is_constant())

    def is_potentially_variable(self):
        return (not self._if.__class__ in native_numeric_types and self._if.is_potentially_variable()) or (not self._then.__class__ in native_numeric_types and self._then.is_potentially_variable()) or (not self._else.__class__ in native_numeric_types and self._else.is_potentially_variable())

    def _polynomial_degree(self, result):
        _if, _then, _else = result
        if _if == 0:
            try:
                return _then if self._if() else _else
            except ValueError:
                pass
        return None

    def _to_string(self, values, verbose=False):
        return 'Expr_if( ( {0} ), then=( {1} ), else=( {2} ) )'.format(self._if, self._then, self._else)

    def _apply_operation(self, result):
        _if, _then, _else = result
        return _then if _if else _else


class UnaryFunctionExpression(ExpressionBase):
    """An object that defines a mathematical expression that can be evaluated"""

    # TODO: Unary functions should define their own subclasses so as to
    # eliminate the need for the fcn and name slots
    __slots__ = ('_fcn', '_name')

    def __init__(self, args, name=None, fcn=None):
        """Construct an expression with an operation and a set of arguments"""
        if not type(args) is tuple:
            args = (args,)
        self._args = args
        self._name = name
        self._fcn = fcn

    def nargs(self):
        return 1

    def construct_node(self, args, memo):
        return self.__class__(args, self._name, self._fcn)

    def __getstate__(self):
        result = super(UnaryFunctionExpression, self).__getstate__()
        for i in UnaryFunctionExpression.__slots__:
            result[i] = getattr(self, i)
        return result

    def getname(self, *args, **kwds):
        return self._name

    def _to_string(self, values, verbose=False):
        if verbose:
            return "{0}({1})".format(self.getname(), values[0])
        return '{0}{1}'.format(self._name, values[0])

    def _polynomial_degree(self, result):
        if result[0] is 0:
            return 0
        else:
            return None

    def _apply_operation(self, result):
        return self._fcn(result[0])


class NPV_UnaryFunctionExpression(UnaryFunctionExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


# NOTE: This should be a special class, since the expression generation relies
# on the Python __abs__ method.
class AbsExpression(UnaryFunctionExpression):

    __slots__ = ()

    def __init__(self, arg):
        super(AbsExpression, self).__init__(arg, 'abs', abs)

    def construct_node(self, args, memo):
        return self.__class__(args)


class NPV_AbsExpression(AbsExpression):
    __slots__ = ()

    def is_potentially_variable(self):
        return False


class _MutableLinearExpression(ExpressionBase):
    __slots__ = ('constant',          # The constant term
                 'linear_coefs',      # Linear coefficients
                 'linear_vars')       # Linear variables

    PRECEDENCE = 6

    def __init__(self, args=None):
        self.constant = 0
        self.linear_coefs = []
        self.linear_vars = []
        self._args = tuple()

    def nargs(self):
        return 0

    def __getstate__(self):
        state = super(_MutableLinearExpression, self).__getstate__()
        for i in _MutableLinearExpression.__slots__:
           state[i] = getattr(self,i)
        return state

    def __deepcopy__(self, memo):
        return self.construct_node(None, memo)

    def construct_node(self, args, memo):
        repn = self.__class__()
        repn.constant = deepcopy(self.constant, memo=memo)
        repn.linear_coefs = deepcopy(self.linear_coefs, memo=memo)
        repn.linear_vars = deepcopy(self.linear_vars, memo=memo)
        return repn

    def getname(self, *args, **kwds):
        return 'sum'

    def _polynomial_degree(self, result):
        return 1 if len(self.linear_vars) > 0 else 0

    def is_constant(self):
        return len(self.linear_vars) == 0

    def is_fixed(self):
        if len(self.linear_vars) == 0:
            return True
        for v in self.linear_vars:
            if v.fixed:
                return True
        return False

    def _to_string(self, values, verbose=False):
        tmp = [str(self.constant)]
        for c,v in zip(self.linear_coefs, self.linear_vars):
            if c.__class__ in native_numeric_types and isclose(value(c),1):
               tmp.append(str(v))
            elif c < 0:
               tmp.append("- %f*%s" % (str(math.fabs(c)),str(v)))
            else:
               tmp.append("+ %f*%s" % (str(c),str(v)))
        return "".join(tmp)

    def is_potentially_variable(self):
        return len(self.linear_vars) > 0

    def _apply_operation(self, result):
        return self.constant + sum(c*v.value for c,v in zip(self.linear_coefs, self.linear_vars))

    #@profile
    @staticmethod
    def _decompose_term(expr):
        if expr.__class__ in native_numeric_types:
            return expr,None,None
        elif expr.__class__ in _MutableLinearExpression.vtypes:
            return 0,1,expr
        elif not expr.is_potentially_variable():
            return expr,None,None
        elif expr.__class__ is ProductExpression:
            if expr._args[0].__class__ in native_numeric_types or not expr._args[0].is_potentially_variable():
                C,c,v = expr._args[0],None,None
            else:
                C,c,v = _MutableLinearExpression._decompose_term(expr._args[0])
            if expr._args[1].__class__ in _MutableLinearExpression.vtypes:
                v_ = expr._args[1]
                if not v is None:
                    raise ValueError("Expected a single linear term (1)")
                return 0,C,v_
            else:
                C_,c_,v_ = _MutableLinearExpression._decompose_term(expr._args[1])
            if not v_ is None:
                if not v is None:
                    raise ValueError("Expected a single linear term (2)")
                return C*C_,C*c_,v_
            return C_*C,C_*c,v
        #
        # A potentially variable _SumExpression class has been supplanted by
        # ViewSumExpression
        #
        #elif expr.__class__ is _SumExpression:
        #    C,c,v = _MutableLinearExpression._decompose_term(expr._args[0])
        #    C_,c_,v_ = _MutableLinearExpression._decompose_term(expr._args[1])
        #    if not v_ is None:
        #        if not v is None:
        #            if id(v) == id(v_):
        #                return C+C_,c+c_,v
        #            else:
        #                raise ValueError("Expected a single linear term (3)")
        #        return C+C_,c_,v_
        #    return C+C_,c,v
        #
        # The _LinearViewSumExpression class is not used now
        #
        #elif expr.__class__ is _LinearViewSumExpression:
        #    C=0
        #    c=1
        #    v=None
        #    for arg in expr.args:
        #        if arg[1] is None:
        #            C += arg[0]
        #        elif not v is None:
        #            raise ValueError("Expected a single linear term (3a)")
        #        else:
        #            c=arg[0]
        #            v=arg[1]
        #    return C,c,v
        elif expr.__class__ is NegationExpression:
            C,c,v = _MutableLinearExpression._decompose_term(expr._args[0])
            return -C,-c,v
        elif expr.__class__ is ReciprocalExpression:
            if expr.is_potentially_variable():
                raise ValueError("Unexpected nonlinear term (4)")
            return 1/expr,None,None
        elif expr.__class__ is _MutableLinearExpression:
            l = len(expr.linear_vars)
            if l == 0:
                return expr.constant, None, None
            elif l == 1:
                return expr.constant, expr.linear_coefs[0], expr.linear_vars[0]
            else:
                raise ValueError("Expected a single linear term (5)")
        elif expr.__class__ is ViewSumExpression or expr.__class__ is _MutableViewSumExpression:
            C = 0
            c = None
            v = None
            for e in expr._args:
                C_,c_,v_ = _MutableLinearExpression._decompose_term(e)
                C += C_
                if not v_ is None:
                    if not v is None:
                        raise ValueError("Expected a single linear term (6)")
                    c=c_
                    v=v_
            return C,c,v
        #
        # TODO: ExprIf, POW, Abs?
        #
        raise ValueError("Unexpected nonlinear term (7)")

    #@profile
    def _combine_expr(self, etype, _other):
        if etype == _add or etype == _sub or etype == -_add or etype == -_sub:
            #
            # if etype == _sub,  then _MutableLinearExpression - VAL
            # if etype == -_sub, then VAL - _MutableLinearExpression
            #
            if etype == _sub:
                omult = -1
            else:
                omult = 1
            if etype == -_sub:
                self.constant *= -1
                for i,c in enumerate(self.linear_coefs):
                    self.linear_coefs[i] = -c

            if _other.__class__ in native_numeric_types or not _other.is_potentially_variable():
                self.constant = self.constant + omult * _other
            elif _other.__class__ is _MutableLinearExpression:
                self.constant = self.constant + omult * _other.constant
                for c,v in zip(_other.linear_coefs, _other.linear_vars):
                    self.linear_coefs.append(omult*c)
                    self.linear_vars.append(v)
            elif _other.__class__ is ViewSumExpression or _other.__class__ is _MutableViewSumExpression:
                for e in _other._args:
                    C,c,v = _MutableLinearExpression._decompose_term(e)
                    self.constant = self.constant + omult * C
                    if not v is None:
                        self.linear_coefs.append(omult*c)
                        self.linear_vars.append(v)
            else:
                C,c,v = _MutableLinearExpression._decompose_term(_other)
                self.constant = self.constant + omult * C
                if not v is None:
                    self.linear_coefs.append(omult*c)
                    self.linear_vars.append(v)

        elif etype == _mul or etype == -_mul:
            if _other.__class__ in native_numeric_types:
                multiplier = _other
            elif _other.is_potentially_variable():
                if len(self.linear_vars) > 0:
                    raise ValueError("Cannot multiply a linear expression with a variable expression")
                #
                # The linear expression is a constant, so re-initialize it with
                # a single term that multiplies the expression by the constant value.
                #
                C,c,v = _MutableLinearExpression._decompose_term(_other)
                self.constant = C*self.constant
                self.linear_vars.append(v)
                self.linear_coefs.append(c*self.constant)
                return self
            else:
                multiplier = _other

            if multiplier.__class__ in native_numeric_types and isclose(multiplier, 0.0):
                self.constant = 0
                self.linear_vars = []
                self.linear_coefs = []
            else:
                self.constant *= multiplier
                for i,c in enumerate(self.linear_coefs):
                    self.linear_coefs[i] = c*multiplier

        elif etype == _div:
            if _other.__class__ in native_numeric_types:
                divisor = _other
            elif self.is_potentially_variable():
                raise ValueError("Unallowed operation on linear expression: division with a variable RHS")
            else:
                divisor = _other
            self.constant /= divisor
            for i,c in enumerate(self.linear_coefs):
                self.linear_coefs[i] = c/divisor

        elif etype == -_div:
            if self.is_potentially_variable():
                raise ValueError("Unallowed operation on linear expression: division with a variable RHS")
            C,c,v = _MutableLinearExpression._decompose_term(_other)
            self.constant = C/self.constant
            if not v is None:
                self.linear_var = [v]
                self.linear_coef = [c/self.constant]
            
        elif etype == _neg:
            self.constant *= -1
            for i,c in enumerate(self.linear_coefs):
                self.linear_coefs[i] = - c

        else:
            raise ValueError("Unallowed operation on mutable linear expression: %d" % etype)

        return self


class LinearExpression(_MutableLinearExpression):
    __slots__ = ()


#-------------------------------------------------------
#
# Functions used to generate expressions
#
#-------------------------------------------------------

def decompose_term(term):
    if term.__class__ in native_numeric_types or not term.is_potentially_variable():
        return True, [(term,None)]
    elif term.__class__ in pyomo5_variable_types:
        return True, [(1,term)]
    else:
        try:
            terms = [t_ for t_ in _decompose_terms(term)]
            return True, terms
        except ValueError:
            return False, None


def _decompose_terms(expr, multiplier=1):
    if expr.__class__ in native_numeric_types or not expr.is_potentially_variable():
        yield (multiplier*expr,None)
    elif expr.__class__ in pyomo5_variable_types:
        yield (multiplier,expr)
    elif expr.__class__ is ProductExpression:
        if expr._args[0].__class__ in native_numeric_types or not expr._args[0].is_potentially_variable():
            for term in _decompose_terms(expr._args[1], multiplier*expr._args[0]):
                yield term
        else:
            raise ValueError("Quadratic terms exist in a product expression.")
    elif expr.__class__ is ReciprocalExpression:
        # The argument is potentially variable, so this represents a nonlinear term
        #
        # NOTE: We're ignoring possible simplifications 
        raise ValueError("Unexpected nonlinear term")
    elif expr.__class__ is ViewSumExpression or expr.__class__ is _MutableViewSumExpression:
        for arg in expr.args:
            for term in _decompose_terms(arg, multiplier):
                yield term
    elif expr.__class__ is NegationExpression:
        for term in  _decompose_terms(expr._args[0], -multiplier):
            yield term
    elif expr.__class__ is LinearExpression or expr.__class__ is _MutableLinearExpression:
        if expr.constant.__class__ in native_numeric_types and not isclose(expr.constant,0):
            yield (multiplier*expr.constant,None)
        if len(expr.linear_coefs) > 0:
            for c,v in zip(expr.linear_coefs, expr.linear_vars):
                yield (multiplier*c,v)
    else:
        raise ValueError("Unexpected nonlinear term")   #pragma: no cover


def _process_arg(obj):
    #if False and obj.__class__ is ViewSumExpression or obj.__class__ is _MutableViewSumExpression:
    #    if ignore_entangled_expressions.detangle[-1] and obj._is_owned:
            #
            # If the viewsum expression is owned, then we need to
            # clone it to avoid creating an entangled expression.
            #
            # But we don't have to worry about entanglement amongst other immutable
            # expression objects.
            #
    #        return clone_expression( obj, clone_leaves=False )
    #    return obj

    #if obj.is_expression():
    #    return obj

    if obj.__class__ is NumericConstant:
        return value(obj)

    if (obj.__class__ is _ParamData or obj.__class__ is SimpleParam) and not obj._component()._mutable:
        if not obj._constructed:
            return obj
        if obj.value is None:
            return obj
        return obj.value

    if obj.is_indexed():
        raise TypeError(
                "Argument for expression is an indexed numeric "
                "value\nspecified without an index:\n\t%s\nIs this "
                "value defined over an index that you did not specify?"
                % (obj.name, ) )

    return obj


#@profile
def generate_sum_expression(etype, _self, _other):

    if etype > _inplace:
        etype -= _inplace

    if _self.__class__ is _MutableLinearExpression:
        if etype >= _unary:
            return _self._combine_expr(etype, None)
        if _other.__class__ is not _MutableLinearExpression:
            if not (_other.__class__ in native_types or _other.is_expression()):
                _other = _process_arg(_other)
        return _self._combine_expr(etype, _other)
    elif _other.__class__ is _MutableLinearExpression:
        if not (_self.__class__ in native_types or _self.is_expression()):
            _self = _process_arg(_self)
        return _other._combine_expr(-etype, _self)

    #
    # A mutable sum is used as a context manager, so we don't
    # need to process it to see if it's entangled.
    #
    if not (_self.__class__ in native_types or _self.is_expression()):
        _self = _process_arg(_self)

    if etype == _neg:
        if _self.__class__ in native_numeric_types:
            return - _self
        elif _self.is_potentially_variable():
            if _self.__class__ is NegationExpression:
                return _self._args[0]
            return NegationExpression((_self,))
        else:
            if _self.__class__ is NPV_NegationExpression:
                return _self._args[0]
            return NPV_NegationExpression((_self,))

    if not (_other.__class__ in native_types or _other.is_expression()):
        _other = _process_arg(_other)

    if etype < 0:
        #
        # This may seem obvious, but if we are performing an
        # "R"-operation (i.e. reverse operation), then simply reverse
        # self and other.  This is legitimate as we are generating a
        # completely new expression here.
        #
        etype *= -1
        _self, _other = _other, _self

    if etype == _add:
        #
        # x + y
        #
        if (_self.__class__ is ViewSumExpression and not _self._shared_args) or \
           _self.__class__ is _MutableViewSumExpression:
            return _self.add(_other)
        elif (_other.__class__ is ViewSumExpression and not _other._shared_args) or \
            _other.__class__ is _MutableViewSumExpression:
            return _other.add(_self)
        elif _other.__class__ in native_numeric_types:
            if _self.__class__ in native_numeric_types:
                return _self + _other
            elif _other == 0:   #isclose(_other, 0):
                return _self
            if _self.is_potentially_variable():
                return ViewSumExpression([_self, _other])
            return NPV_SumExpression((_self, _other))
        elif _self.__class__ in native_numeric_types:
            if _self == 0:      #isclose(_self, 0):
                return _other
            if _other.is_potentially_variable():
                #return _LinearViewSumExpression((_self, _other))
                return ViewSumExpression([_self, _other])
            return NPV_SumExpression((_self, _other))
        elif _other.is_potentially_variable():
            #return _LinearViewSumExpression((_self, _other))
            return ViewSumExpression([_self, _other])
        elif _self.is_potentially_variable():
            #return _LinearViewSumExpression((_other, _self))
            #return ViewSumExpression([_other, _self])
            return ViewSumExpression([_self, _other])
        else:
            return NPV_SumExpression((_self, _other))

    elif etype == _sub:
        #
        # x - y
        #
        if (_self.__class__ is ViewSumExpression and not _self._shared_args) or \
           _self.__class__ is _MutableViewSumExpression:
            return _self.add(-_other)
        elif _other.__class__ in native_numeric_types:
            if _self.__class__ in native_numeric_types:
                return _self - _other
            elif isclose(_other, 0):
                return _self
            if _self.is_potentially_variable():
                #return _LinearViewSumExpression((_self, -_other))
                return ViewSumExpression([_self, -_other])
            return NPV_SumExpression((_self, -_other))
        elif _self.__class__ in native_numeric_types:
            if isclose(_self, 0):
                if _other.is_potentially_variable():
                    return NegationExpression((_other,))
                return NPV_NegationExpression((_other,))
            if _other.is_potentially_variable():    
                #return _LinearViewSumExpression((_self, NegationExpression((_other,))))
                return ViewSumExpression([_self, NegationExpression((_other,))])
            return NPV_SumExpression((_self, NPV_NegationExpression((_other,))))
        elif _other.is_potentially_variable():    
            #return _LinearViewSumExpression((_self, NegationExpression((_other,))))
            return ViewSumExpression([_self, NegationExpression((_other,))])
        elif _self.is_potentially_variable():
            #return _LinearViewSumExpression((_self, NPV_NegationExpression((_other,))))
            return ViewSumExpression([_self, NPV_NegationExpression((_other,))])
        else:
            return NPV_SumExpression((_self, NPV_NegationExpression((_other,))))

    raise RuntimeError("Unknown expression type '%s'" % etype)      #pragma: no cover
        

#@profile
def generate_mul_expression(etype, _self, _other):

    if etype > _inplace:
        etype -= _inplace

    if _self.__class__ is _MutableLinearExpression:
        if _other.__class__ is not _MutableLinearExpression:
            if not (_other.__class__ in native_types or _other.is_expression()):
                _other = _process_arg(_other)
        return _self._combine_expr(etype, _other)
    elif _other.__class__ is _MutableLinearExpression:
        if not (_self.__class__ in native_types or _self.is_expression()):
            _self = _process_arg(_self)
        return _other._combine_expr(-etype, _self)

    #
    # A mutable sum is used as a context manager, so we don't
    # need to process it to see if it's entangled.
    #
    if not (_self.__class__ in native_types or _self.is_expression()):
        _self = _process_arg(_self)

    if not (_other.__class__ in native_types or _other.is_expression()):
        _other = _process_arg(_other)

    if etype < 0:
        #
        # This may seem obvious, but if we are performing an
        # "R"-operation (i.e. reverse operation), then simply reverse
        # self and other.  This is legitimate as we are generating a
        # completely new expression here.
        #
        etype *= -1
        _self, _other = _other, _self

    if etype == _mul:
        #
        # x * y
        #
        if _other.__class__ in native_numeric_types:
            if _self.__class__ in native_numeric_types:
                return _self * _other
            elif _other == 0:   # isclose(_other, 0)
                return 0
            elif _other == 1:
                return _self
            if _self.is_potentially_variable():
                return ProductExpression((_other, _self))
            return NPV_ProductExpression((_self, _other))
        elif _self.__class__ in native_numeric_types:
            if _self == 0:  # isclose(_self, 0)
                return 0
            elif _self == 1:
                return _other
            if _other.is_potentially_variable():
                return ProductExpression((_self, _other))
            return NPV_ProductExpression((_self, _other))
        elif _other.is_potentially_variable():
            return ProductExpression((_self, _other))
        elif _self.is_potentially_variable():
            return ProductExpression((_other, _self))
        else:
            return NPV_ProductExpression((_self, _other))

    elif etype == _div:
        #
        # x / y
        #
        if _other.__class__ in native_numeric_types:
            if _other == 1:
                return _self
            elif not _other:
                raise ZeroDivisionError()
            elif _self.__class__ in native_numeric_types:
                return _self / _other
            if _self.is_potentially_variable():
                return ProductExpression((1/_other, _self))
            return NPV_ProductExpression((1/_other, _self))
        elif _self.__class__ in native_numeric_types:
            if isclose(_self, 0):
                return 0
            elif _self == 1:
                if _other.is_potentially_variable():
                    return ReciprocalExpression((_other,))
                return NPV_ReciprocalExpression((_other,))
            elif _other.is_potentially_variable():
                return ProductExpression((_self, ReciprocalExpression((_other,))))
            return NPV_ProductExpression((_self, ReciprocalExpression((_other,))))
        elif _other.is_potentially_variable():
            return ProductExpression((_self, ReciprocalExpression((_other,))))
        elif _self.is_potentially_variable():
            return ProductExpression((NPV_ReciprocalExpression((_other,)), _self))
        else:
            return NPV_ProductExpression((_self, NPV_ReciprocalExpression((_other,))))

    raise RuntimeError("Unknown expression type '%s'" % etype)      #pragma: no cover


#@profile
def generate_other_expression(etype, _self, _other):

    if etype > _inplace:
        etype -= _inplace

    #
    # A mutable sum is used as a context manager, so we don't
    # need to process it to see if it's entangled.
    #
    if not (_self.__class__ in native_types or _self.is_expression()):
        _self = _process_arg(_self)

    #
    # abs(x)
    #
    if etype == _abs:
        if _self.__class__ in native_numeric_types:
            return abs(_self)
        elif _self.is_potentially_variable():
            return AbsExpression(_self)
        else:
            return NPV_AbsExpression(_self)

    if not (_other.__class__ in native_types or _other.is_expression()):
        _other = _process_arg(_other)

    if etype < 0:
        #
        # This may seem obvious, but if we are performing an
        # "R"-operation (i.e. reverse operation), then simply reverse
        # self and other.  This is legitimate as we are generating a
        # completely new expression here.
        #
        etype *= -1
        _self, _other = _other, _self

    if etype == _pow:
        if _other.__class__ in native_numeric_types:
            if _other == 1:
                return _self
            elif not _other:
                return 1
            elif _self.__class__ in native_numeric_types:
                return _self ** _other
            elif _self.is_potentially_variable():
                return PowExpression((_self, _other))
            return NPV_PowExpression((_self, _other))
        elif _self.__class__ in native_numeric_types:
            if _other.is_potentially_variable():
                return PowExpression((_self, _other))
            return NPV_PowExpression((_self, _other))
        elif _self.is_potentially_variable() or _other.is_potentially_variable():
            return PowExpression((_self, _other))
        else:
            return NPV_PowExpression((_self, _other))

    raise RuntimeError("Unknown expression type '%s'" % etype)      #pragma: no cover


def generate_relational_expression(etype, lhs, rhs):
    # We cannot trust Python not to recycle ID's for temporary POD data
    # (e.g., floats).  So, if it is a "native" type, we will record the
    # value, otherwise we will record the ID.  The tuple for native
    # types is to guarantee that a native value will *never*
    # accidentally match an ID
    cloned_from = (
        id(lhs) if lhs.__class__ not in native_numeric_types else (0,lhs),
        id(rhs) if rhs.__class__ not in native_numeric_types else (0,rhs)
    )
    rhs_is_relational = False
    lhs_is_relational = False

    #
    # TODO: It would be nice to reduce all Constants to literals (and
    # not carry around the overhead of the NumericConstants). For
    # consistency, we will not do that yet, as many things downstream
    # would break; in particular within Constraint.add.  This way, all
    # arguments in the relational Expression's _args will be guaranteed
    # to be NumericValues (just as they are for all other Expressions).
    #
    if not (lhs.__class__ in native_types or lhs.is_expression()):
        lhs = _process_arg(lhs)
    if not (rhs.__class__ in native_types or rhs.is_expression()):
        rhs = _process_arg(rhs)

    if lhs.__class__ in native_numeric_types:
        lhs = as_numeric(lhs)
    elif lhs.is_relational():
        lhs_is_relational = True

    if rhs.__class__ in native_numeric_types:
        rhs = as_numeric(rhs)
    elif rhs.is_relational():
        rhs_is_relational = True

    if InequalityExpression.chainedInequality is not None:
        prevExpr = InequalityExpression.chainedInequality
        match = []
        # This is tricky because the expression could have been posed
        # with >= operators, so we must figure out which arguments
        # match.  One edge case is when the upper and lower bounds are
        # the same (implicit equality) - in which case *both* arguments
        # match, and this should be converted into an equality
        # expression.
        for i,arg in enumerate(prevExpr._cloned_from):
            if arg == cloned_from[0]:
                match.append((i,0))
            elif arg == cloned_from[1]:
                match.append((i,1))
        if etype == _eq:
            raise TypeError(chainedInequalityErrorMessage())
        if len(match) == 1:
            if match[0][0] == match[0][1]:
                raise TypeError(chainedInequalityErrorMessage(
                    "Attempting to form a compound inequality with two "
                    "%s bounds" % ('lower' if match[0][0] else 'upper',)))
            if not match[0][1]:
                cloned_from = prevExpr._cloned_from + (cloned_from[1],)
                lhs = prevExpr
                lhs_is_relational = True
            else:
                cloned_from = (cloned_from[0],) + prevExpr._cloned_from
                rhs = prevExpr
                rhs_is_relational = True
        elif len(match) == 2:
            # Special case: implicit equality constraint posed as a <= b <= a
            if prevExpr._strict[0] or etype == _lt:
                InequalityExpression.chainedInequality = None
                buf = StringIO()
                prevExpr.to_string(buf)
                raise TypeError("Cannot create a compound inequality with "
                      "identical upper and lower\n\tbounds using strict "
                      "inequalities: constraint infeasible:\n\t%s and "
                      "%s < %s" % ( buf.getvalue().strip(), lhs, rhs ))
            if match[0] == (0,0):
                # This is a particularly weird case where someone
                # evaluates the *same* inequality twice in a row.  This
                # should always be an error (you can, for example, get
                # it with "0 <= a >= 0").
                raise TypeError(chainedInequalityErrorMessage())
            etype = _eq
        else:
            raise TypeError(chainedInequalityErrorMessage())
        InequalityExpression.chainedInequality = None

    if etype == _eq:
        if lhs_is_relational or rhs_is_relational:
            buf = StringIO()
            if lhs_is_relational:
                lhs.to_string(buf)
            else:
                rhs.to_string(buf)
            raise TypeError("Cannot create an EqualityExpression where "\
                  "one of the sub-expressions is a relational expression:\n"\
                  "    " + buf.getvalue().strip())
        ans = EqualityExpression((lhs,rhs))
        return ans
    else:
        if etype == _le:
            strict = (False,)
        elif etype == _lt:
            strict = (True,)
        else:
            raise ValueError("Unknown relational expression type '%s'" % etype)
        if lhs_is_relational:
            if lhs.__class__ is InequalityExpression:
                if rhs_is_relational:
                    raise TypeError("Cannot create an InequalityExpression "\
                          "where both sub-expressions are also relational "\
                          "expressions (we support no more than 3 terms "\
                          "in an inequality expression).")
                if len(lhs._args) > 2:
                    raise ValueError("Cannot create an InequalityExpression "\
                          "with more than 3 terms.")
                lhs._args = lhs._args + (rhs,)
                lhs._strict = lhs._strict + strict
                lhs._cloned_from = cloned_from
                return lhs
            else:
                buf = StringIO()
                lhs.to_string(buf)
                raise TypeError("Cannot create an InequalityExpression "\
                      "where one of the sub-expressions is an equality "\
                      "expression:\n    " + buf.getvalue().strip())
        elif rhs_is_relational:
            if rhs.__class__ is InequalityExpression:
                if len(rhs._args) > 2:
                    raise ValueError("Cannot create an InequalityExpression "\
                          "with more than 3 terms.")
                rhs._args = (lhs,) + rhs._args
                rhs._strict = strict + rhs._strict
                rhs._cloned_from = cloned_from
                return rhs
            else:
                buf = StringIO()
                rhs.to_string(buf)
                raise TypeError("Cannot create an InequalityExpression "\
                      "where one of the sub-expressions is an equality "\
                      "expression:\n    " + buf.getvalue().strip())
        else:
            ans = InequalityExpression((lhs, rhs), strict, cloned_from)
            return ans


def generate_intrinsic_function_expression(arg, name, fcn):
    if not (arg.__class__ in native_types or arg.is_expression()):
        arg = _process_arg(arg)

    if arg.__class__ in native_types:
        return fcn(arg)
    elif arg.is_potentially_variable():
        return UnaryFunctionExpression(arg, name, fcn)
    else:
        return NPV_UnaryFunctionExpression(arg, name, fcn)


pyomo5_expression_types = set([
        ExpressionBase,
        NegationExpression,
        NPV_NegationExpression,
        ExternalFunctionExpression,
        NPV_ExternalFunctionExpression,
        PowExpression,
        NPV_PowExpression,
        _LinearOperatorExpression,
        InequalityExpression,
        EqualityExpression,
        ProductExpression,
        NPV_ProductExpression,
        ReciprocalExpression,
        NPV_ReciprocalExpression,
        _SumExpression,
        NPV_SumExpression,
        ViewSumExpression,
        GetItemExpression,
        Expr_if,
        UnaryFunctionExpression,
        NPV_UnaryFunctionExpression,
        AbsExpression,
        NPV_AbsExpression,
        _MutableLinearExpression,
        LinearExpression
        ])
pyomo5_product_types = set([
        ProductExpression,
        NPV_ProductExpression
        ])
pyomo5_reciprocal_types = set([
        ReciprocalExpression,
        NPV_ReciprocalExpression
        ])
pyomo5_variable_types = set()
pyomo5_named_expression_types = set()

