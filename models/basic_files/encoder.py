from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

# We disable pylint because we need python3 compatibility.
from six.moves import xrange  # pylint: disable=redefined-builtin
from six.moves import zip     # pylint: disable=redefined-builtin

from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import control_flow_ops
from tensorflow.python.ops import embedding_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import nn_ops
from . import rnn
from tensorflow.python.ops import variable_scope
from tensorflow.python.util import nest
from . import rnn_cell


""" Vanilla-Attend-Decode model will have only document attention 
(no query as an input), neither the distraction. We will build on top 
of this the other models
"""


# TODO(ebrevdo): Remove once _linear is fully deprecated.
linear = rnn_cell._linear  # pylint: disable=protected-access


def call_rnn_uni_static(cell_encoder,
                        embeddings,
                        dtype):

  encoder_outputs, encoder_state = rnn.rnn(cell_encoder, embeddings, dtype = dtype)
  return encoder_outputs, encoder_state

def call_rnn_uni_dynamic(cell_encoder, 
                         embeddings,
                         sequence_length,
                         dtype):

  
  #print (embeddings[0].get_shape())
  # pack for the time major = False
  embeddings = array_ops.stack(embeddings, axis=1)
  encoder_outputs, encoder_state = rnn.dynamic_rnn(cell_encoder, embeddings, sequence_length, dtype = dtype)

  encoder_outputs = array_ops.unstack(encoder_outputs, axis=1)

  return encoder_outputs, encoder_state

def call_rnn_bidir_static(cell_encoder_fw, 
                          cell_encoder_bw,
                          embeddings,
                          dtype):

  encoder_outputs, encoder_state_fw, encoder_state_bw =  rnn.bidirectional_rnn(
                                                         cell_encoder_fw, cell_encoder_bw,
                                                         embeddings, dtype = dtype)
  
  encoder_state = array_ops.concat([encoder_state_fw, encoder_state_bw],1)

  #encoder_outputs = array_ops.unstack(2, encoder_outputs)
  return encoder_outputs, encoder_state


def call_rnn_bidir_dynamic(cell_encoder_fw,
                           cell_encoder_bw,
                           embeddings, sequence_length,
                           dtype):

  embeddings = array_ops.stack(embeddings, axis=1)
  encoder_outputs, encoder_state = rnn.bidirectional_dynamic_rnn(
                                                        cell_encoder_fw, cell_encoder_bw, 
                                                        embeddings, sequence_length, dtype = dtype)

  encoder_outputs = array_ops.concat(encoder_outputs,2)
  encoder_state = array_ops.concat(encoder_state,1)

  encoder_outputs = array_ops.unstack(encoder_outputs, axis = 1)
  return encoder_outputs, encoder_state

def call_rnn(config,
             cell_encoder_fw,
             cell_encoder_bw,
             embeddings,
             sequence_length,
             dtype):

  if config.config_dir["is_dynamic"] == False and config.config_dir["is_bidir"] == False:
    return call_rnn_uni_static(cell_encoder_fw, embeddings, dtype)

  elif config.config_dir["is_dynamic"] == True and config.config_dir["is_bidir"] == False:
    return call_rnn_uni_dynamic(cell_encoder_fw, embeddings, sequence_length, dtype)

  elif config.config_dir["is_dynamic"] == False and config.config_dir["is_bidir"] == True:
    return call_rnn_bidir_static(cell_encoder_fw, cell_encoder_bw, embeddings, dtype)

  else:
    return call_rnn_bidir_dynamic(cell_encoder_fw, cell_encoder_bw, embeddings, sequence_length, dtype)


def encoder(config,
                    encoder_inputs,
                    query_inputs,
                    cell_encoder_fw,
                    cell_encoder_bw,
                    num_encoder_symbols,
                    embedding_size,
                    initial_embedding = None,
                    num_heads=1,
                    embedding_trainable=False,
                    dtype=None,
                    scope=None,
                    sequence_length_encoder=None,
                    sequence_length_query=None):
  """Embedding sequence-to-sequence model with attention.

  This model first embeds encoder_inputs by a newly created embedding (of shape
  [num_encoder_symbols x input_size]). Then it runs an RNN to encode
  embedded encoder_inputs into a state vector. It keeps the outputs of this
  RNN at every step to use for attention later. Next, it embeds decoder_inputs
  by another newly created embedding (of shape [num_decoder_symbols x
  input_size]). Then it runs attention decoder, initialized with the last
  encoder state, on embedded decoder_inputs and attending to encoder outputs.

  Args:
    encoder_inputs: A list of 1D int32 Tensors of shape [batch_size].
    decoder_inputs: A list of 1D int32 Tensors of shape [batch_size].
    cell: rnn_cell.RNNCell defining the cell function and size.
    num_encoder_symbols: Integer; number of symbols on the encoder side.
    num_decoder_symbols: Integer; number of symbols on the decoder side.
    embedding_size: Integer, the length of the embedding vector for each symbol.
    num_heads: Number of attention heads that read from attention_states.
    output_projection: None or a pair (W, B) of output projection weights and
      biases; W has shape [output_size x num_decoder_symbols] and B has
      shape [num_decoder_symbols]; if provided and feed_previous=True, each
      fed previous output will first be multiplied by W and added B.
    feed_previous: Boolean or scalar Boolean Tensor; if True, only the first
      of decoder_inputs will be used (the "GO" symbol), and all other decoder
      inputs will be taken from previous outputs (as in embedding_rnn_decoder).
      If False, decoder_inputs are used as given (the standard decoder case).
    dtype: The dtype of the initial RNN state (default: tf.float32).
    scope: VariableScope for the created subgraph; defaults to
      "embedding_attention_seq2seq".
    initial_state_attention: If False (default), initial attentions are zero.
      If True, initialize the attentions from the initial state and attention
      states.

  Returns:
    A tuple of the form (outputs, state), where:
      outputs: A list of the same length as decoder_inputs of 2D Tensors with
        shape [batch_size x num_decoder_symbols] containing the generated
        outputs.
      state: The state of each decoder cell at the final time-step.
        It is a 2D Tensor of shape [batch_size x cell.state_size].
  """
  with variable_scope.variable_scope(
      scope or "dynamic_encoder", dtype=dtype) as scope:
    dtype = scope.dtype

    if initial_embedding is not None:
      embedding = variable_scope.get_variable('embedding',
      initializer=initial_embedding, trainable=embedding_trainable)
    
    else:
      embedding = variable_scope.get_variable('embedding', \
                  [num_encoder_symbols, embedding_size],trainable=embedding_trainable)

    
    embedded_inputs = embedding_ops.embedding_lookup(embedding, encoder_inputs)
    embedded_inputs = array_ops.unstack(embedded_inputs)

    query_embeddings = embedding_ops.embedding_lookup(embedding, query_inputs)
    query_embeddings = array_ops.unstack(query_embeddings)

    #print ("Embedded Inputs length:", len(embedded_inputs))
    #print("Shape in embedded inputs:", embedded_inputs[0].get_shape())

    with variable_scope.variable_scope("Encoder_Cell"):
      encoder_outputs, encoder_state = call_rnn(config,
          cell_encoder_fw, cell_encoder_bw, embedded_inputs, sequence_length_encoder, dtype=dtype)

    if config.config_dir["same_cell"] == True:
      with variable_scope.variable_scope("Encoder_Cell", reuse=True):
        query_outputs, query_state = call_rnn(config,
        cell_encoder_fw, cell_encoder_bw, query_embeddings, sequence_length_query, dtype = dtype)

    else:
      with variable_scope.variable_scope("Query_Cell"):
        query_outputs, query_state = call_rnn(config,
        cell_encoder_fw, cell_encoder_bw, query_embeddings, sequence_length_query, dtype = dtype)


    encoder_size = encoder_state.get_shape()[1].value

    top_states_encoder       = [array_ops.reshape(e, [-1, 1, encoder_size])
                                for e in encoder_outputs]
    attention_states_encoder = array_ops.concat(top_states_encoder,1)

    top_states_query       = [array_ops.reshape(e, [-1, 1, encoder_size]) for e in query_outputs]
    attention_states_query = array_ops.concat(top_states_query,1)


    return encoder_state,  attention_states_encoder, query_state, attention_states_query, scope
