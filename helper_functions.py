"""
This file contains a number of different, relatively basic, functions that are used in many different files.
"""

## Basics
import os
import matplotlib.pyplot as plt
from matplotlib.patches import Arc, Ellipse
import matplotlib.colors as mcolors
import numpy as np
import time
import argparse
import re
import pickle

## Sampling
import jax
import jax.numpy as jnp
from jax.config import config
import jax.scipy as jsp
import jax.scipy.stats as jstats
import blackjax as bjx

## Typings
from jax._src.prng import PRNGKeyArray
from jax._src.typing import ArrayLike
from blackjax.types import PyTree
from blackjax.mcmc.rmh import RMHState
from matplotlib import axes as Axes
from typing import Callable, Tuple

## IO-related functions
def print_versions() -> None:
    """"
    Prints functions and which device JAX is using
    """
    print('Using blackjax version', bjx.__version__)
    print('Using JAX version', jax.__version__)
    print(f'Running on {jax.devices()}')

def set_GPU(gpu:str = '') -> None:
    """
    Sets the GPU safely in os.environ, and initializes JAX
    PARAMS:
    gpu : string format of the GPU used. Multiple GPUs can be seperated with commas, e.g. '0,1,2'.
    """
    if gpu is None: # If gpu is None, then all GPUs are used.
        gpu = ''
    os.environ['CUDA_VISIBLE_DEVICES'] = gpu

def get_cmd_params(parameter_list:list) -> dict:
    """
    Gets the parameters described in parameter_list from the command line.
    Returns a dictionary containing the variables with their value, either the value defined in the command line or the default value.
    PARAMS:
    parameter_list : list of tuples containing (arg_name <str>, dest <str>, type <type>, default <any> [*OPTIONAL], nargs <str> [OPTIONAL])
        - arg_name is the name of the argument in the command line.
        - var_name is the name of the variable in the returned dictionary (which we re-use as variable name here).
        - type is the data-type of the variable.
        - default is the default value it takes if nothing is passed to the command line. This argument is only optional if type is bool, where the default is always False.
        - nargs is the number of arguments, where '?' (default) is 1 argument, '+' concatenates all arguments to 1 list. This argument is optional.

        Example of a valid parameter list:
            [('-m', 'mu', float, [1.,0.] '+'),
            ('-s', 'sigma', float, 1.)]
    """
    ## Create parser
    parser = argparse.ArgumentParser()
    ## Add parameters to parser
    for parameter in parameter_list:
        assert len(parameter) in [3, 4, 5], f'Parameter tuple must be length 3 (bool only), 4 or 5 but is length {len(parameter)}.'
        if len(parameter) == 3:
            arg_name, dest, arg_type = parameter
            assert arg_type == bool, f'Three parameters were passed, so arg_type should be bool but is {arg_type}'
            nargs = '?'
        elif len(parameter) == 4:
            arg_name, dest, arg_type, default = parameter
            nargs = '?' # If no nargs is given we default to single value
        elif len(parameter) == 5:
            arg_name, dest, arg_type, default, nargs = parameter
        if arg_type != bool:
            parser.add_argument(arg_name, dest=dest, nargs=nargs, type=arg_type, default=default)
        else:
            parser.add_argument(arg_name, dest=dest, action='store_true', default=False)
    ## Parse arguments from CMD
    args = parser.parse_args()
    ## Create global parameters dictionary
    global_params = {arg:getattr(args,arg) for arg in vars(args)}
    return global_params

def get_filename_with_ext(base_filename:str, partial:bool=False, bpf:bool=False, ext:str='pkl', folder:str='.') -> str:
    """
    Returns the filename of a file based on the base filename and a bunch of possible boolean parameters.
    Used to keep file naming consistent between different pieces of code.
    E.g. {base_filename}_partial_bpf.pkl if all parameters are true.
    PARAMS:
    base_filename : the base name of the output file
    partial : whether to use partial correlations
    bpf : whether to use band-pass filtered rs-fMRI data
    ext : file extension
    """
    partial_txt = '_partial' if partial else ''
    bpf_txt = '_bpf' if bpf else ''
    return f"{folder}/{base_filename}{partial_txt}{bpf_txt}.{ext}"

def get_safe_folder(folder:str) -> str:
    """
    Creates a folder if it did not yet exists along the path given, and simply returns the folder name.
    PARAMS:
    folder : folder which should exist
    """
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder

def get_plt_labels(label_location:str, make_plot:bool, no_labels:bool, N:int) -> ArrayLike:
    """
    Returns the label location and checks for label validity.
    PARAMS:
    label_location : the location of the labels file
    make_plot : whether to make a plot (used since plt labels are unnecessary if no plot is made).
    no_labels : whether to use labels
    N : number of nodes
    """
    if make_plot and not no_labels:
        label_data = np.load(label_location)
        plt_labels = label_data[label_data.files[0]]
        if len(plt_labels) != N:
            plt_labels = None
    else:
        plt_labels = None
    return plt_labels

def key2str(key:PRNGKeyArray) -> str:
    """
    Returns the string version of the final entry in the PRNGKeyArray.
    PARAMS:
    key : JAX random key
    """
    numbers = re.findall(r"[0-9]+", str(key))
    return numbers[-1]

def is_valid(x:ArrayLike) -> Tuple[bool, np.array]:
    """
    Checks whether all values in an array are finite, and returns whether this is the case and the indices of infinite values.
    PARAMS:
    x : input array
    """
    return jnp.all(jnp.isfinite(x)), jnp.where(jnp.logical_not(jnp.isfinite(x)))

def create_task_file(filename:str, n_tasks:int, n_observations:int=1, delim:str=',') -> None:
    """
    Creates a task file which can later be used by load_observations. Used when creating simulated data. 
    PARAMS:
    filename : name of the task file
    n_tasks : number of "tasks"
    n_observations : number of observations
    delim : delimiter between the tasks and observations in the task file
    """
    task_str = delim.join([f'T{i}' for i in range(n_tasks)])
    obs_str = delim.join([f'obs{i}' for i in range(n_observations)])
    with open(filename, 'w') as f:
        f.write(f'{task_str}\n')
        f.write(obs_str)

def open_taskfile(task_filename:str) -> Tuple[list, list]:
    """
    Opens the task file and return the tasks and encodings in a list
    PARAMS:
    task_filename : the path to the task file
    """
    with open(task_filename) as tf:
        tasks = tf.readline().rstrip('\n').split(',')
        encs = tf.readline().rstrip('\n').split(',')
    return tasks, encs

def load_observations(data_filename:str, task_filename:str, subject1:int, subjectn:int, M:int, abs:bool=True) -> Tuple[np.ndarray, list, list]:
    """
    Loads the observations from the filename into a jax.numpy array, seperated by task found in task_filename. Takes both encodings as seperate observations of the same stimulus.
    Returns the full (n_subjects, n_tasks, n_encs, n_edges) observation matrix, the list of task names, and the list of encoding direction names.
    PARAMS:
    data_filename : filename of the observed correlations data
    task_filename : name of the file containing a list of tasks plus a list of encodings (=observations per subject per task)
    subject1 : first subject
    subjectn : last subject
    M : number of edges
    abs : whether to take the absolute correlations
    """
    ## Open the data and task files
    with open(data_filename, 'rb') as f:
        obs_corr_dict = pickle.load(f)
    tasks, encs = open_taskfile(task_filename)

    ## Get observations for each subject for each task
    n_subjects = subjectn+1-subject1
    n_tasks = len(tasks)
    obs = np.zeros((n_subjects, n_tasks, len(encs), M))

    ## Create the observations matrix
    for si, n_sub in enumerate(range(subject1, subjectn+1)):
        for ti, task in enumerate(tasks):
            for ei, enc in enumerate(encs):
                dict_key = f'S{n_sub}_{task}_{enc}'
                observed_values = jnp.abs(obs_corr_dict[dict_key]) if abs else obs_corr_dict[dict_key]
                obs[si, ti, ei, :] = observed_values
    return obs, tasks, encs

## Data manipulation
def node_pos_dict2array(pos_dict:dict) -> np.ndarray:
    """
    Puts the dictionary latent positions {node: position} into an (N,D) array
    PARAMS:
    pos_dict : dictionary containing node integers as keys and positions (length D) as value
    """
    N = len(pos_dict)
    D = len(pos_dict[0])
    pos_array = np.zeros((N, D))
    for i in range(N):
        pos_array[i, :] = pos_dict[i]
    return pos_array

def triu2mat(v:ArrayLike) -> ArrayLike:
    """
    Fills a matrix from the upper triangle vector
    PARAMS:
    v (ArrayLike) : upper triangle vector
    """
    m = len(v)
    n = int((1 + np.sqrt(1 + 8 * m))/2)
    mat = jnp.zeros((n, n))
    triu_indices = jnp.triu_indices(n, k=1)
    mat = mat.at[triu_indices].set(v)
    return mat + mat.T

def get_trace_correlation(sampled_d:ArrayLike, ground_truth_d:ArrayLike) -> ArrayLike:
    """
    Gets the correlations between the distances in the sampled positions and the ground truth.
    PARAMS:
    sampled_d : the sampled distance matrices (n_samples, N, N) or (n_samples, M)
    ground_truth_d : the ground truth distance matrix (N, N) or (M)
    """
    if len(sampled_d.shape) == 3:
        N = sampled_d.shape[1]
        d_idc = triu_indices
    elif len(sampled_d.shape) == 2:
        M = sampled_d.shape[1]
        N = int((1 + np.sqrt(1 + 8 * M))/2)
        d_idc = np.arange(M)
    triu_indices = np.triu_indices(N, k=1)
    if len(ground_truth_d.shape) == 2:
        ground_truth_d = ground_truth_d[triu_indices]
    get_corr = lambda carry, d: (None, jnp.corrcoef(ground_truth_d, d[d_idc])[0, 1])
    _, corrs = jax.lax.scan(get_corr, None, sampled_d)
    return corrs

def get_attribute_from_trace(LSM_embeddings:ArrayLike, get_det_params:Callable, attribute:str='d', shape:tuple=None, param_kwargs:dict={}) -> jnp.ndarray:
    """
    Gets a given attribute for a whole trace of positions
    PARAMS:
    LSM_embeddings : (T, n_particles, N, D) or (n_particles, N, D) latent positions for all traces of all embeddings
    get_det_params : function to get the deterministic parameters according to the correct model
    attributes : dictionary key corresponding to the desired attribute
    shape : shape of the output, T x n_particles x "shape of attribute for 1 particle"
    param_kwargs : parameters for the get_det_params function (e.g. {'mu' : [0.,0.]})
    """
    ## Get embedding ready in the same shape
    if len(LSM_embeddings.shape) == 4:
        T, n_particles, N, _ = LSM_embeddings.shape
    elif len(LSM_embeddings.shape) == 3:
        n_particles, N, _ = LSM_embeddings.shape
        T = 1
        LSM_embeddings = jnp.array([LSM_embeddings])
    else:
        print(f'Illegal format for LSM_embeddings: {LSM_embeddings.shape}')

    if shape is None:
        M = N * (N - 1) // 2
        shape = (T, n_particles, M)
    elif T == 1:
        shape = (T,) + shape

    ## Define while-loop functions
    def cond(carry):
        k, _, _ = carry
        return k < T

    @jax.jit
    def step(carry):
        """
        PARAMS:
        carry
            k : the index over embeddings
            i : the index over particles
            attributes : the carried-over matrix of calculated attributes
        """
        k, i, attributes = carry
        attributes = attributes.at[k,i,:].set(get_det_params(LSM_embeddings[k,i,:,:], **param_kwargs)[attribute])
        i = (i+1)%n_particles
        k = k+ (i == 0)
        return k, i, attributes

    ## Run while-loop
    _, _, attributes = jax.lax.while_loop(cond, step, (0, 0, jnp.zeros(shape)))
    return attributes[0] if T == 1 else attributes

## Math functions
def logit(x:ArrayLike) -> ArrayLike:
    """
    Definition of the logit function. 
    PARAMS:
    x : input variables
    """
    return jnp.log(1/(1-x))

def invlogit(x:ArrayLike) -> ArrayLike:
    """
    Definition of the inverse-logit function (a.k.a. the logistic function)
    PARAMS:
    x : input variables
    """
    return 1 / (1 + jnp.exp(-x))

def euclidean_distance(z:ArrayLike) -> jnp.ndarray:
    """
    Returns the Euclidean distance between all elements in z, calculated via the Gram matrix.
    PARAMS:
    z : (N,D) latent positions
    """
    G = jnp.dot(z, z.T)
    g = jnp.diag(G)
    ones = jnp.ones_like(g)
    inside = jnp.maximum(jnp.outer(ones, g) + jnp.outer(g, ones) - 2 * G, 0)
    return jnp.sqrt(inside)

def lorentz_to_poincare(networks:ArrayLike) -> np.ndarray:
    """
    Convert Lorentz coordinates to Poincaré coordinates, eq. 11 from Nickel & Kiela (2018).
    PARAMS:
    network (S,N,D) or (N,D): numpy array with Lorentzian coordinates [samples x nodes x dimensions] or [nodes x dimensions]
    """
    ## Assure networks has the correct shape
    one_nw = len(networks.shape) == 2
    if one_nw:
        networks = np.array([networks])

    ## Convert Lorentz positions to Poincaré positions
    S, N, D_L = networks.shape
    calc_z_P = lambda c, nw: (None, nw[:,1:]/np.reshape(np.repeat(nw[:,0]+1, D_L-1), newshape=(N, D_L-1)))
    _, z_P = jax.lax.scan(calc_z_P, None, networks)

    return z_P[0] if one_nw else z_P

def hyp_pnt(X:ArrayLike) -> jnp.ndarray:
    """
    Creates [z,x,y] positions in hyperbolic space by projecting [x,y] positions onto hyperbolic plane directly by solving the equation defining the hyperbolic plane.
    PARAMS
    X : array containing 2D points to be projected up onto the hyperbolic plane
    """
    N, D = X.shape
    z = jnp.sqrt(jnp.sum(X**2, axis=1)+1)
    x_hyp = jnp.zeros((N,D+1))
    x_hyp = x_hyp.at[:,0].set(z)
    x_hyp = x_hyp.at[:,1:].set(X)
    return x_hyp

def lorentzian(v:ArrayLike, u:ArrayLike, keepdims:bool=False) -> jnp.ndarray:
    """
    Returns the Lorentzian prodcut of v and u, defined as -v_0*u_0 + SUM_{i=1}^N v_i*u_i
    PARAMS:
    v : (N,D) vector
    u : (N,D) vector
    keepdims : whether to keep the same number of dimensions (True), or flatten the new array.
    """
    signs = jnp.ones_like(v)
    signs = signs.at[:,0].set(-1)
    return jnp.sum(v*u*signs, axis=1, keepdims=keepdims)

def lorentz_distance(z:ArrayLike) -> jnp.ndarray:
    """
    Returns the hyperbolic distance between all N points in z as an N x N matrix.
    PARAMS:
    z : (N,D) points in hyperbolic space
    """
    def arccosh(x:ArrayLike) -> jnp.ndarray:
        """
        Definition of the arccosh function
        PARAMS:
        x : input
        """
        x_clip = jnp.maximum(x, jnp.ones_like(x, dtype=jnp.float32))
        return jnp.log(x_clip + jnp.sqrt(x_clip**2 - 1))
    signs = jnp.ones_like(z)
    signs = signs.at[:,0].set(-1)
    lor = jnp.dot(signs*z, z.T)
    ## Due to numerical instability, we can get NaN's on the diagonal, hence we force the diagonal to be zero.
    dist = arccosh(-lor)
    dist = dist.at[jnp.diag_indices_from(dist)].set(0)
    return dist

def parallel_transport(v:ArrayLike, nu:ArrayLike, mu:ArrayLike) -> ArrayLike:
    """
    Parallel transports the points v sampled around nu to the tangent space of mu.
    PARAMS:
    v  (N,D) : points on tangent space of nu [points on distribution around nu]
    nu (N,D) : point in hyperbolic space [center to move from] (mu_0 in Fig 2 of Nagano et al. (2019))
    mu (N,D) : point in hyperbolic space [center to move to]
    """
    alpha = -lorentzian(nu, mu, keepdims=True)
    u = v + lorentzian(mu - alpha*nu, v, keepdims=True)/(alpha+1) * (nu + mu)
    return u

def exponential_map(mu:ArrayLike, u:ArrayLike, eps:float=1e-6) -> ArrayLike:
    """
    Maps the points v on the tangent space of mu onto the hyperolic plane
    PARAMS:
    mu (N,D) : Transported middle points
    u (N,D) : Points to be mapped onto hyperbolic space (after parallel transport)
    eps : minimum value for the norm of u
    """
    ## Euclidean norm from mu_0 to v is the same as from mu to u is the same as the hyperbolic norm from mu to exp_mu(u), hence we can use the Euclidean norm of v.
    lor = lorentzian(u,u,keepdims=True)
    u_norm = jnp.sqrt(jnp.clip(lor, eps, lor))  ## If eps is too small, u_norm gets rounded right back to zero and then we divide by zero
    return jnp.cosh(u_norm) * mu + jnp.sinh(u_norm) * u / u_norm

