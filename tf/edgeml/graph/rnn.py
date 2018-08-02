# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT license.

import numpy as np
import tensorflow as tf
from tensorflow.python.ops import init_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import variable_scope as vs
from tensorflow.python.ops import gen_math_ops
from tensorflow.python.ops.rnn_cell_impl import RNNCell


def gen_non_linearity(A, non_linearity):
    '''
    Returns required activation for a tensor based on the inputs
    '''
    if non_linearity == "tanh":
        return math_ops.tanh(A)
    elif non_linearity == "sigmoid":
        return math_ops.sigmoid(A)
    elif non_linearity == "relu":
        return gen_math_ops.maximum(A, 0.0)
    elif non_linearity == "quantTanh":
        return gen_math_ops.maximum(gen_math_ops.minimum(A, 1.0), -1.0)
    elif non_linearity == "quantSigm":
        A = (A + 1.0) / 2.0
        return gen_math_ops.maximum(gen_math_ops.minimum(A, 1.0), 0.0)
    else:
        return math_ops.tanh(A)


class FastGRNNCell(RNNCell):
    '''
    FastGRNN Cell with Both Full Rank and Low Rank Formulations
    Has multiple activation functions for the gates
    '''

    def __init__(self, hidden_size, gate_non_linearity="sigmoid",
                 update_non_linearity="tanh", wRank=None, uRank=None,
                 zetaInit=1.0, nuInit=-4.0, name="FastGRNN"):
        super(FastGRNNCell, self).__init__()
        self._hidden_size = hidden_size
        self._gate_non_linearity = gate_non_linearity
        self._update_non_linearity = update_non_linearity
        self._num_weight_matrices = [1, 1]
        self._wRank = wRank
        self._uRank = uRank
        self._zetaInit = zetaInit
        self._nuInit = nuInit
        if wRank is not None:
            self._num_weight_matrices[0] += 1
        if uRank is not None:
            self._num_weight_matrices[1] += 1
        self._name = name

    @property
    def state_size(self):
        return self._hidden_size

    def output_size(self):
        return self._hidden_size

    def gate_non_linearity(self):
        return self._gate_non_linearity

    def update_non_linearity(self):
        return self._update_non_linearity

    def wRank(self):
        return self._wRank

    def uRank(self):
        return self._uRank

    def num_weight_matrices(self):
        return self._num_weight_matrices

    def name(self):
        return self._name

    def cellType(self):
        return "FastGRNN"

    def call(self, inputs, state):
        with vs.variable_scope(self._name + "/FastGRNNcell"):

            if self._wRank is None:
                W_matrix_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.W = vs.get_variable(
                    "W", [inputs.get_shape()[-1], self._hidden_size],
                    initializer=W_matrix_init)
                wComp = math_ops.matmul(inputs, self.W)
            else:
                W_matrix_1_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.W1 = vs.get_variable(
                    "W1", [inputs.get_shape()[-1], self._wRank],
                    initializer=W_matrix_1_init)
                W_matrix_2_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.W2 = vs.get_variable(
                    "W2", [self._wRank, self._hidden_size],
                    initializer=W_matrix_2_init)
                wComp = math_ops.matmul(
                    math_ops.matmul(inputs, self.W1), self.W2)

            if self._uRank is None:
                U_matrix_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.U = vs.get_variable(
                    "U", [self._hidden_size, self._hidden_size],
                    initializer=U_matrix_init)
                uComp = math_ops.matmul(state, self.U)
            else:
                U_matrix_1_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.U1 = vs.get_variable(
                    "U1", [self._hidden_size, self._uRank],
                    initializer=U_matrix_1_init)
                U_matrix_2_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.U2 = vs.get_variable(
                    "U2", [self._uRank, self._hidden_size],
                    initializer=U_matrix_2_init)
                uComp = math_ops.matmul(
                    math_ops.matmul(state, self.U1), self.U2)
            # Init zeta to 6.0 and nu to -6.0 if this doesn't give good
            # results. The ints are hyper-params.
            zeta_init = init_ops.constant_initializer(
                self._zetaInit, dtype=tf.float32)
            self.zeta = vs.get_variable("zeta", [1, 1], initializer=zeta_init)

            nu_init = init_ops.constant_initializer(
                self._nuInit, dtype=tf.float32)
            self.nu = vs.get_variable("nu", [1, 1], initializer=nu_init)

            pre_comp = wComp + uComp

            bias_gate_init = init_ops.constant_initializer(
                1.0, dtype=tf.float32)
            self.bias_gate = vs.get_variable(
                "B_g", [1, self._hidden_size], initializer=bias_gate_init)
            z = gen_non_linearity(pre_comp + self.bias_gate,
                                  self._gate_non_linearity)

            bias_update_init = init_ops.constant_initializer(
                1.0, dtype=tf.float32)
            self.bias_update = vs.get_variable(
                "B_h", [1, self._hidden_size], initializer=bias_update_init)
            c = gen_non_linearity(
                pre_comp + self.bias_update, self._update_non_linearity)

            new_h = z * state + (math_ops.sigmoid(self.zeta) * (1.0 - z) +
                                 math_ops.sigmoid(self.nu)) * c
        return new_h, new_h

    def getVars(self):
        Vars = []
        if self._num_weight_matrices[0] == 1:
            Vars.append(self.W)
        else:
            Vars.extend([self.W1, self.W2])

        if self._num_weight_matrices[1] == 1:
            Vars.append(self.U)
        else:
            Vars.extend([self.U1, self.U2])

        Vars.extend([self.bias_gate, self.bias_update])
        Vars.extend([self.zeta, self.nu])

        return Vars


class FastRNNCell(RNNCell):
    '''
    FastRNN Cell with Both Full Rank and Low Rank Formulations
    Has multiple activation functions for the gates
    '''

    def __init__(self, hidden_size, update_non_linearity="tanh",
                 wRank=None, uRank=None, alphaInit=-3.0, betaInit=3.0, name="FastRNN"):
        super(FastRNNCell, self).__init__()
        self._hidden_size = hidden_size
        self._update_non_linearity = update_non_linearity
        self._num_weight_matrices = [1, 1]
        self._wRank = wRank
        self._uRank = uRank
        self._alphaInit = alphaInit
        self._betaInit = betaInit
        if wRank is not None:
            self._num_weight_matrices[0] += 1
        if uRank is not None:
            self._num_weight_matrices[1] += 1
        self._name = name

    @property
    def state_size(self):
        return self._hidden_size

    def output_size(self):
        return self._hidden_size

    def update_non_linearity(self):
        return self._update_non_linearity

    def wRank(self):
        return self._wRank

    def uRank(self):
        return self._uRank

    def num_weight_matrices(self):
        return self._num_weight_matrices

    def name(self):
        return self._name

    def cellType(self):
        return "FastRNN"

    def call(self, inputs, state):
        with vs.variable_scope(self._name + "/FastRNNcell"):

            if self._wRank is None:
                W_matrix_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.W = vs.get_variable(
                    "W", [inputs.get_shape()[-1], self._hidden_size],
                    initializer=W_matrix_init)
                wComp = math_ops.matmul(inputs, self.W)
            else:
                W_matrix_1_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.W1 = vs.get_variable(
                    "W1", [inputs.get_shape()[-1], self._wRank],
                    initializer=W_matrix_1_init)
                W_matrix_2_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.W2 = vs.get_variable(
                    "W2", [self._wRank, self._hidden_size],
                    initializer=W_matrix_2_init)
                wComp = math_ops.matmul(
                    math_ops.matmul(inputs, self.W1), self.W2)

            if self._uRank is None:
                U_matrix_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.U = vs.get_variable(
                    "U", [self._hidden_size, self._hidden_size],
                    initializer=U_matrix_init)
                uComp = math_ops.matmul(state, self.U)
            else:
                U_matrix_1_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.U1 = vs.get_variable(
                    "U1", [self._hidden_size, self._uRank],
                    initializer=U_matrix_1_init)
                U_matrix_2_init = init_ops.random_normal_initializer(
                    mean=0.0, stddev=0.1, dtype=tf.float32)
                self.U2 = vs.get_variable(
                    "U2", [self._uRank, self._hidden_size],
                    initializer=U_matrix_2_init)
                uComp = math_ops.matmul(
                    math_ops.matmul(state, self.U1), self.U2)

            alpha_init = init_ops.constant_initializer(
                self._alphaInit, dtype=tf.float32)
            self.alpha = vs.get_variable(
                "alpha", [1, 1], initializer=alpha_init)

            beta_init = init_ops.constant_initializer(
                self._betaInit, dtype=tf.float32)
            self.beta = vs.get_variable("beta", [1, 1], initializer=beta_init)

            pre_comp = wComp + uComp

            bias_update_init = init_ops.constant_initializer(
                1.0, dtype=tf.float32)
            self.bias_update = vs.get_variable(
                "B_h", [1, self._hidden_size], initializer=bias_update_init)
            c = gen_non_linearity(
                pre_comp + self.bias_update, self._update_non_linearity)

            new_h = math_ops.sigmoid(self.beta) * \
                state + math_ops.sigmoid(self.alpha) * c
        return new_h, new_h

    def getVars(self):
        Vars = []
        if self._num_weight_matrices[0] == 1:
            Vars.append(self.W)
        else:
            Vars.extend([self.W1, self.W2])

        if self._num_weight_matrices[1] == 1:
            Vars.append(self.U)
        else:
            Vars.extend([self.U1, self.U2])

        Vars.extend([self.bias_update])
        Vars.extend([self.alpha, self.beta])

        return Vars


class EMI_DataPipeline():
    '''The datainput block for EMI-RNN training. Since EMI-RNN is an expensive
    algorithm due to the multiple rounds of updates that are to be performed,
    we avoid using the feed dict to feed data into tensorflow and rather,
    exploit the dataset API. This class abstracts most of the details of these
    implementations. This class uses iterators to iterate over the data in
    batches.

    This class uses reinitializable iterators. Please refer to the dataset API
    docs for more information.

    This class supports resuming from checkpoint files. Provide the restored
    meta graph as an argument to __init__ to enable this behaviour

    Usage:
        Step 1: Create a data input pipeline object and obtain the x_batch and
        y_batch tensors. These shoudl be fed to other parts of the graph which
        acts on the input data.
        ```
            inputPipeline = EMI_DataPipeline(NUM_SUBINSTANCE, NUM_TIMESTEPS,
                                             NUM_FEATS, NUM_OUTPUT)
            x_batch, y_batch = inputPipeline()
            # feed to emiLSTM or some other computation subgraph
            y_cap = emiLSTM(x_batch)
        ```

        Step 2:  Create other parts of the computation graph (loss operations,
        training ops etc). After initializing the tensorflow grpah with
        global_variables_initializer, initialize the iterator with the input
        data by calling:
            inputPipeline.runInitializer(x_train, y_trian..)

        Step 3: You can now iterate over batches by runing some computation
        operation. At the end of the data, tf.errors.OutOfRangeError will be
        thrown.
        ```
        while True:
            try:
                sess.run(y_cap)
            except tf.errors.OutOfRangeError:
                break
        ```
    '''

    def __init__(self, numSubinstance, numTimesteps, numFeats, numOutput,
                 graph=None, prefetchNum=5):
        '''
        numSubinstance, numTimeSteps, numFeats, numOutput:
            Dataset characteristis. Please refer to the associated EMI_RNN
            publication for more information.
        graph: This module supports resuming/restoring from a saved metagraph. To
            enable this behaviour, pass the restored graph as an argument.
        prefetchNum: The number of asynchrenous prefetch to do when iterating over
            the data. Please refer to 'prefetching' in tensorflow dataset API
        '''

        self.numSubinstance = numSubinstance
        self.numTimesteps = numTimesteps
        self.numFeats = numFeats
        self.graph = graph
        self.prefetchNum = prefetchNum
        self.numOutput = numOutput
        self.graphCreated = False
        # Either restore or create the following
        self.X = None
        self.Y = None
        self.batchSize = None
        self.numEpochs = None
        self.dataset_init = None
        self.x_batch = None
        self.y_batch = None
        # Internal
        self.scope = 'EMI/'

    def __createGraph(self):
        assert self.graphCreated is False
        dim = [None, self.numSubinstance, self.numTimesteps, self.numFeats]
        scope = self.scope + 'input-pipeline/'
        with tf.name_scope(scope):
            X = tf.placeholder(tf.float32, dim, name='inpX')
            Y = tf.placeholder(tf.float32, [None, self.numSubinstance,
                                            self.numOutput], name='inpY')
            batchSize = tf.placeholder(tf.int64, name='batch-size')
            numEpochs = tf.placeholder(tf.int64, name='num-epochs')

            dataset_x_target = tf.data.Dataset.from_tensor_slices(X)
            dataset_y_target = tf.data.Dataset.from_tensor_slices(Y)
            couple = (dataset_x_target, dataset_y_target)
            ds_target = tf.data.Dataset.zip(couple).repeat(numEpochs)
            ds_target = ds_target.batch(batchSize)
            ds_target = ds_target.prefetch(self.prefetchNum)
            ds_iterator_target = tf.data.Iterator.from_structure(ds_target.output_types,
                                                                 ds_target.output_shapes)
            ds_next_target = ds_iterator_target
            ds_init_target = ds_iterator_target.make_initializer(ds_target,
                                                                 name='dataset-init')
            x_batch, y_batch = ds_iterator_target.get_next()
            tf.add_to_collection('next-x-batch', x_batch)
            tf.add_to_collection('next-y-batch', y_batch)
        self.X = X
        self.Y = Y
        self.batchSize = batchSize
        self.numEpochs = numEpochs
        self.dataset_init = ds_init_target
        self.x_batch, self.y_batch = x_batch, y_batch
        self.graphCreated = True

    def __restoreGraph(self, graph):
        assert self.graphCreated is False
        scope = 'EMI/input-pipeline/'
        self.X = graph.get_tensor_by_name(scope + "inpX:0")
        self.Y = graph.get_tensor_by_name(scope + "inpY:0")
        self.batchSize = graph.get_tensor_by_name(scope + "batch-size:0")
        self.numEpochs = graph.get_tensor_by_name(scope + "num-epochs:0")
        self.dataset_init = graph.get_operation_by_name(scope + "dataset-init")
        self.x_batch = graph.get_collection('next-x-batch')
        self.y_batch = graph.get_collection('next-y-batch')
        msg = 'More than one tensor named next-x-batch/next-y-batch. '
        msg += 'Are you not resetting your graph?'
        assert len(self.x_batch) == 1, msg
        assert len(self.y_batch) == 1, msg
        self.x_batch = self.x_batch[0]
        self.y_batch = self.y_batch[0]
        self.graphCreated = True

    def __call__(self):
        if self.graphCreated is True:
            return self.x_batch, self.y_batch
        if self.graph is None:
            self.__createGraph()
        else:
            self.__restoreGraph(self.graph)
        assert self.graphCreated is True
        return self.x_batch, self.y_batch

    def restoreFromGraph(self, graph, *args, **kwargs):
        self.graphCreated = False
        self.graph = graph
        self.__restoreGraph(graph)
        assert self.graphCreated is True

    def runInitializer(self, sess, x_data, y_data, batchSize, numEpochs):
        '''
        Initializes the dataset API with the input data (x_data, y_data).

        x_data, y_data, batchSize: Self explanatory
        numEpochs: The dataset API implements epochs by appending the data to
            itself numEpochs times and then iterating over the resulting data as if
            it was a single data set.
        '''
        assert self.graphCreated is True
        msg = 'X shape should be [-1, numSubinstance, numTimesteps, numFeats]'
        assert x_data.ndim == 4, msg
        assert x_data.shape[1] == self.numSubinstance, msg
        assert x_data.shape[2] == self.numTimesteps, msg
        assert x_data.shape[3] == self.numFeats, msg
        msg = 'X and Y sould have same first dimension'
        assert y_data.shape[0] == x_data.shape[0], msg
        msg = 'Y shape should be [-1, numSubinstance, numOutput]'
        assert y_data.shape[1] == self.numSubinstance, msg
        assert y_data.shape[2] == self.numOutput, msg
        feed_dict = {
            self.X: x_data,
            self.Y: y_data,
            self.batchSize: batchSize,
            self.numEpochs: numEpochs
        }
        assert self.dataset_init is not None, 'Internal error!'
        sess.run(self.dataset_init, feed_dict=feed_dict)


class EMI_RNN():
    """Abstract base class for RNN architectures compatible with EMI-RNN. This
    class is extended by specific architectures like LSTM/GRU/FastGRNN etc.

    Note: We are not using the PEP recommended abc module since it is difficult
    to support in both python 2 and 3
    """

    def __init__(self, *args, **kwargs):
        self.graphCreated = False
        # Model specific matrices, parameter should be saved
        self.graph = None
        self.varList = []
        self.output = None
        self.assignOps = []
        raise NotImplementedError("This is intended to act similar to an " +
                                  "abstract class. Instantiating is not " +
                                  "allowed.")

    def __call__(self, *args, **kwargs):
        if self.graphCreated is True:
            assert self.output is not None
            return self.output
        if self.graph is None:
            output = self._createBaseGraph(*args, **kwargs)
            assert self.graphCreated is False
            self._createExtendedGraph(output, *args, **kwargs)
        else:
            self._restoreBaseGraph(self.graph, *args, **kwargs)
            assert self.graphCreated is False
            self._restoreExtendedGraph(self.graph, *args, **kwargs)
        assert self.graphCreated is True
        return self.output

    def restoreFromGraph(self, graph, *args, **kwargs):
        self.graphCreated = False
        self.varList = []
        self.output = None
        self.assignOps = []
        self.graph = graph
        self._restoreBaseGraph(self.graph, *args, **kwargs)
        assert self.graphCreated is False
        self._restoreExtendedGraph(self.graph, *args, **kwargs)
        assert self.graphCreated is True

    def getHyperParams(self):
        raise NotImplementedError("Subclass does not implement this method")

    def _createBaseGraph(self, *args, **kwargs):
        raise NotImplementedError("Subclass does not implement this method")

    def _createExtendedGraph(self, baseOutput, *args, **kwargs):
        raise NotImplementedError("Subclass does not implement this method")

    def _restoreBaseGraph(self, graph, *args, **kwargs):
        raise NotImplementedError("Subclass does not implement this method")

    def _restoreExtendedGraph(self, graph, *args, **kwargs):
        raise NotImplementedError("Subclass does not implement this method")

    def addBaseAssignOps(self, graph, *args, **kwargs):
        raise NotImplementedError("Subclass does not implement this method")

    def addExtendedAssignOps(self, graph, *args, **kwargs):
        raise NotImplementedError("Subclass does not implement this method")


class EMI_BasicLSTM(EMI_RNN):
    """EMI-RNN/MI-RNN model using LSTM.
    """

    def __init__(self, numSubinstance, numHidden, numTimeSteps,
                 numFeats, graph=None, forgetBias=1.0, useDropout=False):
        self.numHidden = numHidden
        self.numTimeSteps = numTimeSteps
        self.numFeats = numFeats
        self.useDropout = useDropout
        self.forgetBias = forgetBias
        self.numSubinstance = numSubinstance
        self.graph = graph
        self.graphCreated = False
        # Restore or initialize
        self.keep_prob = None
        self.varList = []
        self.output = None
        self.assignOps = []
        # Internal
        self._scope = 'EMI/BasicLSTM/'

    def _createBaseGraph(self, X):
        assert self.graphCreated is False
        msg = 'X should be of form [-1, numSubinstance, numTimeSteps, numFeatures]'
        assert X.get_shape().ndims == 4, msg
        assert X.shape[1] == self.numSubinstance
        assert X.shape[2] == self.numTimeSteps
        assert X.shape[3] == self.numFeats
        # Reshape into 3D suself.h that the first dimension is -1 * numSubinstance
        # where each numSubinstance segment corresponds to one bag
        # then shape it back in into 4D
        scope = self._scope
        keep_prob = None
        with tf.name_scope(scope):
            x = tf.reshape(X, [-1, self.numTimeSteps, self.numFeats])
            x = tf.unstack(x, num=self.numTimeSteps, axis=1)
            # Get the LSTM output
            cell = tf.nn.rnn_cell.BasicLSTMCell(self.numHidden,
                                                forget_bias=self.forgetBias,
                                                name='EMI-LSTM-Cell')
            wrapped_cell = cell
            if self.useDropout is True:
                keep_prob = tf.placeholder(dtype=tf.float32, name='keep-prob')
                wrapped_cell = tf.contrib.rnn.DropoutWrapper(cell,
                                                             input_keep_prob=keep_prob,
                                                             output_keep_prob=keep_prob)
            outputs__, states = tf.nn.static_rnn(
                wrapped_cell, x, dtype=tf.float32)
            outputs = []
            for output in outputs__:
                outputs.append(tf.expand_dims(output, axis=1))
            # Convert back to bag form
            outputs = tf.concat(outputs, axis=1, name='concat-output')
            dims = [-1, self.numSubinstance, self.numTimeSteps, self.numHidden]
            output = tf.reshape(outputs, dims, name='bag-output')

        LSTMVars = cell.variables
        self.varList.extend(LSTMVars)
        if self.useDropout:
            self.keep_prob = keep_prob
        self.output = output
        return self.output

    def _restoreBaseGraph(self, graph, X):
        assert self.graphCreated is False
        assert self.graph is not None
        scope = self._scope
        if self.useDropout:
            self.keep_prob = graph.get_tensor_by_name(scope + 'keep-prob:0')
        self.output = graph.get_tensor_by_name(scope + 'bag-output:0')
        kernel = graph.get_tensor_by_name("rnn/EMI-LSTM-Cell/kernel:0")
        bias = graph.get_tensor_by_name("rnn/EMI-LSTM-Cell/bias:0")
        assert len(self.varList) is 0
        self.varList = [kernel, bias]

    def getHyperParams(self):
        assert self.graphCreated is True, "Graph is not created"
        assert len(self.varList) == 2
        return self.varList

    def addBaseAssignOps(self, initVarList):
        assert initVarList is not None
        assert len(initVarList) == 2
        k_ = graph.get_tensor_by_name('rnn/EMI-LSTM-Cell/kernel:0')
        b_ = graph.get_tensor_by_name('rnn/EMI-LSTM-Cell/bias:0')
        kernel, bias = initVarList[-2], initVarList[-1]
        k_op = tf.assign(k_, kernel)
        b_op = tf.assign(b_, bias)
        self.assignOps.extend([k_op, b_op])


class EMI_GRU(EMI_RNN):
    """EMI-RNN/MI-RNN model using GRU.
    """

    def __init__(self, numSubinstance, numHidden, numTimeSteps,
                 numFeats, graph=None, useDropout=False):
        self.numHidden = numHidden
        self.numTimeSteps = numTimeSteps
        self.numFeats = numFeats
        self.useDropout = useDropout
        self.numSubinstance = numSubinstance
        self.graph = graph
        self.graphCreated = False
        # Restore or initialize
        self.keep_prob = None
        self.varList = []
        self.output = None
        self.assignOps = []
        # Internal
        self._scope = 'EMI/GRU/'

    def _createBaseGraph(self, X):
        assert self.graphCreated is False
        msg = 'X should be of form [-1, numSubinstance, numTimeSteps, numFeatures]'
        assert X.get_shape().ndims == 4, msg
        assert X.shape[1] == self.numSubinstance
        assert X.shape[2] == self.numTimeSteps
        assert X.shape[3] == self.numFeats
        # Reshape into 3D suself.h that the first dimension is -1 * numSubinstance
        # where each numSubinstance segment corresponds to one bag
        # then shape it back in into 4D
        scope = self._scope
        keep_prob = None
        with tf.name_scope(scope):
            x = tf.reshape(X, [-1, self.numTimeSteps, self.numFeats])
            x = tf.unstack(x, num=self.numTimeSteps, axis=1)
            # Get the GRU output
            cell = tf.nn.rnn_cell.GRUCell(self.numHidden, name='EMI-GRU-Cell')
            wrapped_cell = cell
            if self.useDropout is True:
                keep_prob = tf.placeholder(dtype=tf.float32, name='keep-prob')
                wrapped_cell = tf.contrib.rnn.DropoutWrapper(cell,
                                                             input_keep_prob=keep_prob,
                                                             output_keep_prob=keep_prob)
            outputs__, states = tf.nn.static_rnn(
                wrapped_cell, x, dtype=tf.float32)
            outputs = []
            for output in outputs__:
                outputs.append(tf.expand_dims(output, axis=1))
            # Convert back to bag form
            outputs = tf.concat(outputs, axis=1, name='concat-output')
            dims = [-1, self.numSubinstance, self.numTimeSteps, self.numHidden]
            output = tf.reshape(outputs, dims, name='bag-output')

        GRUVars = cell.variables
        self.varList.extend(GRUVars)
        if self.useDropout:
            self.keep_prob = keep_prob
        self.output = output
        return self.output

    def _restoreBaseGraph(self, graph, X):
        assert self.graphCreated is False
        assert self.graph is not None
        scope = self._scope
        if self.useDropout:
            self.keep_prob = graph.get_tensor_by_name(scope + 'keep-prob:0')
        self.output = graph.get_tensor_by_name(scope + 'bag-output:0')
        kernel1 = graph.get_tensor_by_name("rnn/EMI-GRU-Cell/gates/kernel:0")
        bias1 = graph.get_tensor_by_name("rnn/EMI-GRU-Cell/gates/bias:0")
        kernel2 = graph.get_tensor_by_name(
            "rnn/EMI-GRU-Cell/candidate/kernel:0")
        bias2 = graph.get_tensor_by_name("rnn/EMI-GRU-Cell/candidate/bias:0")
        assert len(self.varList) is 0
        self.varList = [kernel1, bias1, kernel2, bias2]

    def getHyperParams(self):
        assert self.graphCreated is True, "Graph is not created"
        assert len(self.varList) == 4
        return self.varList

    def addBaseAssignOps(self, initVarList):
        assert initVarList is not None
        assert len(initVarList) == 2
        kernel1_ = graph.get_tensor_by_name("rnn/EMI-GRU-Cell/gates/kernel:0")
        bias1_ = graph.get_tensor_by_name("rnn/EMI-GRU-Cell/gates/bias:0")
        kernel2_ = graph.get_tensor_by_name(
            "rnn/EMI-GRU-Cell/candidate/kernel:0")
        bias2_ = graph.get_tensor_by_name("rnn/EMI-GRU-Cell/candidate/bias:0")
        kernel1, bias1, kernel2, bias2 = initVarList[
            0], initVarList[1], initVarList[2], initVarList[3]
        kernel1_op = tf.assign(kernel1_, kernel1)
        bias1_op = tf.assign(bias1_, bias1)
        kernel2_op = tf.assign(kernel2_, kernel2)
        bias2_op = tf.assign(bias2_, bias2)
        self.assignOps.extend([kernel1_op, bias1_op, kernel2_op, bias2_op])


class EMI_FastRNN(EMI_RNN):
    """EMI-RNN/MI-RNN model using FastRNN.
    """

    def __init__(self, numSubinstance, numHidden, numTimeSteps,
                 numFeats, graph=None, useDropout=False, update_non_linearity="tanh",
                 wRank=None, uRank=None, alphaInit=-3.0, betaInit=3.0):
        self.numHidden = numHidden
        self.numTimeSteps = numTimeSteps
        self.numFeats = numFeats
        self.useDropout = useDropout
        self.numSubinstance = numSubinstance
        self.graph = graph

        self.update_non_linearity = update_non_linearity
        self.wRank = wRank
        self.uRank = uRank
        self.alphaInit = alphaInit
        self.betaInit = betaInit

        self.graphCreated = False
        # Restore or initialize
        self.keep_prob = None
        self.varList = []
        self.output = None
        self.assignOps = []
        # Internal
        self._scope = 'EMI/FastRNN/'

    def _createBaseGraph(self, X):
        assert self.graphCreated is False
        msg = 'X should be of form [-1, numSubinstance, numTimeSteps, numFeatures]'
        assert X.get_shape().ndims == 4, msg
        assert X.shape[1] == self.numSubinstance
        assert X.shape[2] == self.numTimeSteps
        assert X.shape[3] == self.numFeats
        # Reshape into 3D suself.h that the first dimension is -1 * numSubinstance
        # where each numSubinstance segment corresponds to one bag
        # then shape it back in into 4D
        scope = self._scope
        keep_prob = None
        with tf.name_scope(scope):
            x = tf.reshape(X, [-1, self.numTimeSteps, self.numFeats])
            x = tf.unstack(x, num=self.numTimeSteps, axis=1)
            # Get the FastRNN output
            cell = FastRNNCell(self.numHidden, self.update_non_linearity,
                               self.wRank, self.uRank, self.alphaInit, self.betaInit, name='EMI-FastRNN-Cell')
            wrapped_cell = cell
            if self.useDropout is True:
                keep_prob = tf.placeholder(dtype=tf.float32, name='keep-prob')
                wrapped_cell = tf.contrib.rnn.DropoutWrapper(cell,
                                                             input_keep_prob=keep_prob,
                                                             output_keep_prob=keep_prob)
            outputs__, states = tf.nn.static_rnn(
                wrapped_cell, x, dtype=tf.float32)
            outputs = []
            for output in outputs__:
                outputs.append(tf.expand_dims(output, axis=1))
            # Convert back to bag form
            outputs = tf.concat(outputs, axis=1, name='concat-output')
            dims = [-1, self.numSubinstance, self.numTimeSteps, self.numHidden]
            output = tf.reshape(outputs, dims, name='bag-output')

        FastRNNVars = cell.variables
        self.varList.extend(FastRNNVars)
        if self.useDropout:
            self.keep_prob = keep_prob
        self.output = output
        return self.output

    def _restoreBaseGraph(self, graph, X):
        assert self.graphCreated is False
        assert self.graph is not None
        scope = self._scope
        if self.useDropout:
            self.keep_prob = graph.get_tensor_by_name(scope + 'keep-prob:0')
        self.output = graph.get_tensor_by_name(scope + 'bag-output:0')

        assert len(self.varList) is 0
        if self.wRank is None:
            W = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/W:0")
            self.varList = [W]
        else:
            W1 = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/W1:0")
            W2 = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/W2:0")
            self.varList = [W1, W2]

        if self.uRank is None:
            U = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/U:0")
            self.varList.extend([U])
        else:
            U1 = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/U1:0")
            U2 = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/U2:0")
            self.varList.extend([U1, U2])

        alpha = graph.get_tensor_by_name(
            "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/alpha:0")
        beta = graph.get_tensor_by_name(
            "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/beta:0")
        bias = graph.get_tensor_by_name(
            "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/B_h:0")
        self.varList.extend([alpha, beta, bias])

    def getHyperParams(self):
        assert self.graphCreated is True, "Graph is not created"
        return self.varList

    def addBaseAssignOps(self, initVarList):
        assert initVarList is not None
        index = 0
        if self.wRank is None:
            W_ = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/W:0")
            W = initVarList[0]
            w_op = tf.assign(W_, W)
            self.assignOps.extend([w_op])
            index += 1
        else:
            W1_ = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/W1:0")
            W2_ = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/W2:0")
            W1, W2 = initVarList[0], initVarList[1]
            w1_op = tf.assign(W1_, W1)
            w2_op = tf.assign(W2_, W2)
            self.assignOps.extend([w1_op, w2_op])
            index += 2

        if self.uRank is None:
            U_ = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/U:0")
            U = initVarList[index]
            u_op = tf.assign(U_, U)
            self.assignOps.extend([u_op])
            index += 1
        else:
            U1_ = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/U1:0")
            U2_ = graph.get_tensor_by_name(
                "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/U2:0")
            U1, U2 = initVarList[index], initVarList[index + 1]
            u1_op = tf.assign(U1_, U1)
            u2_op = tf.assign(U2_, U2)
            self.assignOps.extend([u1_op, u2_op])
            index += 2

        alpha_ = graph.get_tensor_by_name(
            "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/alpha:0")
        beta_ = graph.get_tensor_by_name(
            "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/beta:0")
        bias_ = graph.get_tensor_by_name(
            "rnn/fast_rnn_cell/EMI-FastRNN-Cell/FastRNNcell/B_h:0")

        alpha, beta, bias = initVarList[index], initVarList[
            index + 1], initVarList[index + 2]
        alpha_op = tf.assign(alpha_, alpha)
        beta_op = tf.assign(beta_, beta)
        bias_op = tf.assign(bias_, bias)

        self.assignOps.extend([alpha_op, beta_op, bias_op])


class EMI_UGRNN(EMI_RNN):
    """EMI-RNN/MI-RNN model using UGRNN.
    """

    def __init__(self, numSubinstance, numHidden, numTimeSteps,
                 numFeats, graph=None, forgetBias=1.0, useDropout=False):
        self.numHidden = numHidden
        self.numTimeSteps = numTimeSteps
        self.numFeats = numFeats
        self.useDropout = useDropout
        self.forgetBias = forgetBias
        self.numSubinstance = numSubinstance
        self.graph = graph
        self.graphCreated = False
        # Restore or initialize
        self.keep_prob = None
        self.varList = []
        self.output = None
        self.assignOps = []
        # Internal
        self._scope = 'EMI/UGRNN/'

    def _createBaseGraph(self, X):
        assert self.graphCreated is False
        msg = 'X should be of form [-1, numSubinstance, numTimeSteps, numFeatures]'
        assert X.get_shape().ndims == 4, msg
        assert X.shape[1] == self.numSubinstance
        assert X.shape[2] == self.numTimeSteps
        assert X.shape[3] == self.numFeats
        # Reshape into 3D suself.h that the first dimension is -1 * numSubinstance
        # where each numSubinstance segment corresponds to one bag
        # then shape it back in into 4D
        scope = self._scope
        keep_prob = None
        with tf.name_scope(scope):
            x = tf.reshape(X, [-1, self.numTimeSteps, self.numFeats])
            x = tf.unstack(x, num=self.numTimeSteps, axis=1)
            # Get the UGRNN output
            cell = tf.contrib.rnn.UGRNNCell(self.numHidden,
                                            forget_bias=self.forgetBias)
            wrapped_cell = cell
            if self.useDropout is True:
                keep_prob = tf.placeholder(dtype=tf.float32, name='keep-prob')
                wrapped_cell = tf.contrib.rnn.DropoutWrapper(cell,
                                                             input_keep_prob=keep_prob,
                                                             output_keep_prob=keep_prob)
            outputs__, states = tf.nn.static_rnn(
                wrapped_cell, x, dtype=tf.float32)
            outputs = []
            for output in outputs__:
                outputs.append(tf.expand_dims(output, axis=1))
            # Convert back to bag form
            outputs = tf.concat(outputs, axis=1, name='concat-output')
            dims = [-1, self.numSubinstance, self.numTimeSteps, self.numHidden]
            output = tf.reshape(outputs, dims, name='bag-output')

        UGRNNVars = cell.variables
        self.varList.extend(UGRNNVars)
        if self.useDropout:
            self.keep_prob = keep_prob
        self.output = output
        return self.output

    def _restoreBaseGraph(self, graph, X):
        assert self.graphCreated is False
        assert self.graph is not None
        scope = self._scope
        if self.useDropout:
            self.keep_prob = graph.get_tensor_by_name(scope + 'keep-prob:0')
        self.output = graph.get_tensor_by_name(scope + 'bag-output:0')
        kernel = graph.get_tensor_by_name("rnn/ugrnn_cell/kernel:0")
        bias = graph.get_tensor_by_name("rnn/ugrnn_cell/bias:0")
        assert len(self.varList) is 0
        self.varList = [kernel, bias]

    def getHyperParams(self):
        assert self.graphCreated is True, "Graph is not created"
        assert len(self.varList) == 2
        return self.varList

    def addBaseAssignOps(self, initVarList):
        assert initVarList is not None
        assert len(initVarList) == 2
        k_ = graph.get_tensor_by_name('rnn/ugrnn_cell/kernel:0')
        b_ = graph.get_tensor_by_name('rnn/ugrnn_cell/bias:0')
        kernel, bias = initVarList[-2], initVarList[-1]
        k_op = tf.assign(k_, kernel)
        b_op = tf.assign(b_, bias)
        self.assignOps.extend([k_op, b_op])


class EMI_FastGRNN(EMI_RNN):
    """EMI-RNN/MI-RNN model using FastGRNN.
    """

    def __init__(self, numSubinstance, numHidden, numTimeSteps,
                 numFeats, graph=None, useDropout=False, gate_non_linearity="sigmoid",
                 update_non_linearity="tanh", wRank=None, uRank=None,
                 zetaInit=1.0, nuInit=-4.0):
        self.numHidden = numHidden
        self.numTimeSteps = numTimeSteps
        self.numFeats = numFeats
        self.useDropout = useDropout
        self.numSubinstance = numSubinstance
        self.graph = graph

        self.gate_non_linearity = gate_non_linearity
        self.update_non_linearity = update_non_linearity
        self.wRank = wRank
        self.uRank = uRank
        self.zetaInit = zetaInit
        self.nuInit = nuInit

        self.graphCreated = False
        # Restore or initialize
        self.keep_prob = None
        self.varList = []
        self.output = None
        self.assignOps = []
        # Internal
        self._scope = 'EMI/FastGRNN/'

    def _createBaseGraph(self, X):
        assert self.graphCreated is False
        msg = 'X should be of form [-1, numSubinstance, numTimeSteps, numFeatures]'
        assert X.get_shape().ndims == 4, msg
        assert X.shape[1] == self.numSubinstance
        assert X.shape[2] == self.numTimeSteps
        assert X.shape[3] == self.numFeats
        # Reshape into 3D suself.h that the first dimension is -1 * numSubinstance
        # where each numSubinstance segment corresponds to one bag
        # then shape it back in into 4D
        scope = self._scope
        keep_prob = None
        with tf.name_scope(scope):
            x = tf.reshape(X, [-1, self.numTimeSteps, self.numFeats])
            x = tf.unstack(x, num=self.numTimeSteps, axis=1)
            # Get the FastGRNN output
            cell = FastGRNNCell(self.numHidden, self.gate_non_linearity, self.update_non_linearity,
                                self.wRank, self.uRank, self.zetaInit, self.nuInit, name='EMI-FastGRNN-Cell')
            wrapped_cell = cell
            if self.useDropout is True:
                keep_prob = tf.placeholder(dtype=tf.float32, name='keep-prob')
                wrapped_cell = tf.contrib.rnn.DropoutWrapper(cell,
                                                             input_keep_prob=keep_prob,
                                                             output_keep_prob=keep_prob)
            outputs__, states = tf.nn.static_rnn(
                wrapped_cell, x, dtype=tf.float32)
            outputs = []
            for output in outputs__:
                outputs.append(tf.expand_dims(output, axis=1))
            # Convert back to bag form
            outputs = tf.concat(outputs, axis=1, name='concat-output')
            dims = [-1, self.numSubinstance, self.numTimeSteps, self.numHidden]
            output = tf.reshape(outputs, dims, name='bag-output')

        FastGRNNVars = cell.variables
        self.varList.extend(FastGRNNVars)
        if self.useDropout:
            self.keep_prob = keep_prob
        self.output = output
        return self.output

    def _restoreBaseGraph(self, graph, X):
        assert self.graphCreated is False
        assert self.graph is not None
        scope = self._scope
        if self.useDropout:
            self.keep_prob = graph.get_tensor_by_name(scope + 'keep-prob:0')
        self.output = graph.get_tensor_by_name(scope + 'bag-output:0')

        assert len(self.varList) is 0
        if self.wRank is None:
            W = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/W:0")
            self.varList = [W]
        else:
            W1 = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/W1:0")
            W2 = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/W2:0")
            self.varList = [W1, W2]

        if self.uRank is None:
            U = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/U:0")
            self.varList.extend([U])
        else:
            U1 = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/U1:0")
            U2 = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/U2:0")
            self.varList.extend([U1, U2])

        zeta = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/zeta:0")
        nu = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/nu:0")
        gate_bias = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/B_g:0")
        update_bias = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/B_h:0")
        self.varList.extend([zeta, nu, gate_bias, update_bias])

    def getHyperParams(self):
        assert self.graphCreated is True, "Graph is not created"
        return self.varList

    def addBaseAssignOps(self, initVarList):
        assert initVarList is not None
        index = 0
        if self.wRank is None:
            W_ = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/W:0")
            W = initVarList[0]
            w_op = tf.assign(W_, W)
            self.assignOps.extend([w_op])
            index += 1
        else:
            W1_ = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/W1:0")
            W2_ = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/W2:0")
            W1, W2 = initVarList[0], initVarList[1]
            w1_op = tf.assign(W1_, W1)
            w2_op = tf.assign(W2_, W2)
            self.assignOps.extend([w1_op, w2_op])
            index += 2

        if self.uRank is None:
            U_ = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/U:0")
            U = initVarList[index]
            u_op = tf.assign(U_, U)
            self.assignOps.extend([u_op])
            index += 1
        else:
            U1_ = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/U1:0")
            U2_ = graph.get_tensor_by_name(
                "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/U2:0")
            U1, U2 = initVarList[index], initVarList[index + 1]
            u1_op = tf.assign(U1_, U1)
            u2_op = tf.assign(U2_, U2)
            self.assignOps.extend([u1_op, u2_op])
            index += 2

        zeta_ = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/zeta:0")
        nu_ = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/nu:0")
        gate_bias_ = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/B_g:0")
        update_bias_ = graph.get_tensor_by_name(
            "rnn/fast_grnn_cell/EMI-FastGRNN-Cell/FastGRNNcell/B_h:0")

        zeta, nu, gate_bias, update_bias = initVarList[index], initVarList[
            index + 1], initVarList[index + 2], initVarList[index + 3]
        zeta_op = tf.assign(zeta_, zeta)
        nu_op = tf.assign(nu_, nu)
        gate_bias_op = tf.assign(gate_bias_, gate_bias)
        update_bias_op = tf.assign(update_bias_, update_bias)

        self.assignOps.extend([zeta_op, nu_op, gate_bias_op, update_bias_op])
