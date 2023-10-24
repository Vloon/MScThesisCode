# Home brew functions
from helper_functions import set_GPU, get_cmd_params, get_filename_with_ext, get_safe_folder, load_observations, \
    get_attribute_from_trace, euclidean_distance
from bookstein_methods import get_bookstein_anchors, bookstein_position, smc_bookstein_position, add_bkst_to_smc_trace
from plotting_functions import plot_posterior, plot_network

# Basics
import pickle
import time
import os
import csv
import numpy as np

import matplotlib.pyplot as plt

# Sampling
import jax
import jax.numpy as jnp
import jax.scipy.stats as jstats
import blackjax as bjx
import blackjax.smc.resampling as resampling

# Typing
from jax._src.prng import PRNGKeyArray
from jax._src.typing import ArrayLike
from blackjax.types import PyTree
from blackjax.mcmc.rmh import RMHState
from blackjax.smc.tempered import TemperedSMCState
from blackjax.smc.base import SMCInfo
from typing import Callable, Tuple

# Keep this here in case you somehow import the file and need these constants??
eps = 1e-6
obs_eps = 1e-12
mu = [0., 0.]
sigma = 1.
N = 164
D = 2
s1 = 1
sn = 25
n_particles = 1_000
n_mcmc_steps = 100
rmh_sigma = 1e-2
bookstein_dist = 0.3
base_data_filename = 'processed_data_bin'
task_filename = 'task_list.txt'
base_output_folder = 'Embeddings'
make_plot = False
figure_folder = 'Figures'
label_location = 'Figures/lobelabels.npz'
plot_threshold = .4
do_print = False
save_stats = False
stats_filename = 'statistics'
stats_folder = 'Statistics'
dl = ';'
seed_file = 'seed.txt'
seed = None
gpu = ''

if __name__ == "__main__":
    # Create cmd argument list (arg_name, var_name, type, default, nargs[OPT])
    arguments = [('-e', 'eps', float, eps),  # d->d_max offset
                 ('-obseps', 'obs_eps', float, obs_eps),  # observation clipping offset
                 ('-m', 'mu', float, mu, '+'),  # mean of distribution to sample z
                 ('-s', 'sigma', float, sigma),  # std of distribution to sample z
                 ('-N', 'N', int, N),  # number of nodes
                 ('-D', 'D', int, D),  # latent space dimensions
                 ('-s1', 'subject1', int, s1),  # first subject to be used
                 ('-sn', 'subjectn', int, sn),  # last subject to be used
                 ('-np', 'n_particles', int, n_particles),  # number of smc particles
                 ('-nm', 'n_mcmc_steps', int, n_mcmc_steps),  # number of mcmc steps within smc
                 ('-r', 'rmh_sigma', float, rmh_sigma),  # sigma of the RMH sampler within SMC
                 ('-bdist', 'bookstein_dist', float, bookstein_dist),  # distance between the bookstein anchors
                 ('-overwritedf', 'overwrite_data_filename', str, None),  # if used, it overwrites the default filename
                 ('-df', 'base_data_filename', str, base_data_filename),  # filename of the saved data
                 ('-tf', 'task_filename', str, task_filename),  # filename of the list of task names
                 ('-of', 'base_output_folder', str, base_output_folder),  # folder where to dump the LSM embeddings
                 ('--plot', 'make_plot', bool),  # whether to create a plot
                 ('-ff', 'figure_folder', str, figure_folder),  # base folder where to dump the figures
                 ('-lab', 'label_location', str, label_location),  # file location of the labels
                 ('-plotth', 'plot_threshold', float, plot_threshold),  # threshold for plotting edges
                 ('--print', 'do_print', bool),  # whether to print cute info
                 ('--stats', 'save_stats', bool),  # whether to save the statistics in a csv
                 ('--partial', 'partial', bool),  # whether to use partial correlations
                 ('--bpf', 'bpf', bool),  # whether to use band-pass filtered rs-fMRI data
                 ('-stf', 'stats_filename', str, stats_filename),  # statistics filename
                 ('-stfl', 'stats_folder', str, stats_folder),  # statistics folder
                 ('-dl', 'dl', str, dl),  # save stats delimeter
                 ('-seedfile', 'seed_file', str, seed_file),  # save file for the seed
                 ('-seed', 'seed', int, seed),  # starting random key
                 ('-gpu', 'gpu', str, gpu), # number of gpu to use (in string form). If no GPU is specified, CPU is used.
                 ]

    # Get arguments from CMD
    global_params = get_cmd_params(arguments)
    eps = global_params['eps']
    obs_eps = global_params['obs_eps']
    mu = global_params['mu']
    sigma = global_params['sigma']
    N = global_params['N']
    M = N * (N - 1) // 2
    D = global_params['D']
    subject1 = global_params['subject1']
    subjectn = global_params['subjectn']
    n_particles = global_params['n_particles']
    n_mcmc_steps = global_params['n_mcmc_steps']
    rmh_sigma = global_params['rmh_sigma']
    bookstein_dist = global_params['bookstein_dist']
    overwrite_data_filename = global_params['overwrite_data_filename']
    base_data_filename = global_params['base_data_filename']
    task_filename = global_params['task_filename']
    output_folder = get_safe_folder(f"{global_params['base_output_folder']}/{n_particles}p{n_mcmc_steps}s")
    make_plot = global_params['make_plot']
    figure_folder = get_safe_folder(f"{global_params['figure_folder']}/{n_particles}p{n_mcmc_steps}s")
    label_location = global_params['label_location']
    plot_threshold = global_params['plot_threshold']
    do_print = global_params['do_print']
    save_stats = global_params['save_stats']
    partial = global_params['partial']
    bpf = global_params['bpf']
    stats_folder = get_safe_folder(stats_folder)
    stats_filename = get_filename_with_ext(global_params['stats_filename'], ext='csv', folder=stats_folder)
    dl = global_params['dl']
    seed_file = global_params['seed_file']
    seed = global_params['seed']
    set_GPU(global_params['gpu'])

    # Initialize JAX stuff
    if do_print:
        print('Using blackjax version', bjx.__version__)
        print(f'Running on {jax.devices()}')
    if seed is None:
        with open(seed_file, 'r') as f:
            seed = int(f.read())
    key = jax.random.PRNGKey(seed)

    # ONLY NOW TURN MU INTO JNP ARRAY, OTHERWISE JAX WILL F*** WITH THE GPUs THE WRONG WAY!!
    mu = jnp.array(mu)

## Define functions to calculate the continuous hyperbolic parameters
def get_det_params(z:ArrayLike, eps:float=eps) -> dict:
    """ 
    Calculates all parameters based on z, and returns those in a dictionary.
    PARAMS:
    z : positions on the Euclidean plane 
    eps : offset for calculating d_norm, to insure max(d_norm) < 1
    """ 
    N = z.shape[0]
    triu_indices = jnp.triu_indices(N, k=1)

    d = euclidean_distance(z)[triu_indices]
    d_norm = d/(jnp.max(d)+eps) 

    p = 1-d_norm

    params = {'z':z,
              'd':d,
              'd_norm':d_norm,
              'p':p}
    return params

## Sampling functions
def sample_prior(key:PRNGKeyArray, shape:tuple, mu:float = mu, sigma:float = sigma, eps:float = eps) -> Tuple[PRNGKeyArray, dict]:
    """ 
    Samples a prior by taking a 2D normal distribution and solving for z on the hyperbolic plane. 
    Returns the prior parameters in a dictionary.
    PARAMS:
    key : Random key for JAX functions
    shape : shape of the prior positions
    mu : mean of the 2D Gaussian to sample p
    sigma : standard deviation of the 2D Gaussian to sample p
    eps : offset for calculating d_norm, to insure max(d_norm) < 1
    """
    N = shape[0]
    M = N * (N - 1) // 2

    # Sample positions and temp
    key, z_key = jax.random.split(key, num=2)
    prior = {'z': sigma * jax.random.normal(z_key, shape=shape) + mu}

    return key, prior

def sample_observation(key:PRNGKeyArray, prior:dict, n_samples:int=1, eps:float=eps) -> Tuple[PRNGKeyArray, jnp.array]:
    """ 
    Generates an observation based on the prior
    PARAMS:
    key : Random key for JAX functions
    prior : dictionary containing sampled variables from the prior ('z', 'T')
    n_samples : number of observations to sample
    eps : offset for the normalization of d, and clipping of A
    """
    # Get prior position and sigma
    z = prior['z']
    N = z.shape[0] 
    M = N*(N-1)//2

    # Calculate p
    params = get_det_params(z, eps=eps)
    p = params['p']

    # Sample A
    key, subkey = jax.random.split(key)
    A = jax.random.bernoulli(subkey, p, shape=(n_samples, M))

    return key, A

## Probability distributions
def log_prior(z:ArrayLike, mu:float=mu, sigma:float=sigma) -> float:
    """
    Returns the log-prior
    PARAMS:
    z : positions on the Euclidean plane
    mu : mean of the 2D Gaussian to sample z
    sigma : standard deviation of the 2D Gaussian to sample z
    """
    logprob_z = jstats.norm.logpdf(z, loc=mu, scale=sigma).sum()
    return logprob_z

def bookstein_log_prior(z:ArrayLike, mu:float=mu, sigma:float=sigma) -> float:
    """
    Returns the log-prior for a network with bookstein coordinates
    PARAMS:
    z : positions on Euclidean plane
    mu : mean of the 2D Gaussian to sample _z
    sigma : standard deviation of the 2D Gaussian to sample _z
    """
    rest_logprior = log_prior(z[1:,:], mu, sigma)
    pivot_point_logprior = jnp.log(2)+jstats.norm.logpdf(z[0,:], loc=mu, scale=sigma).sum() + np.NINF*(z[0,1] < 0.) # log[2*N(_z[2]|mu,sigma)] if _z[2] >= 0 else -INF.
    return rest_logprior + pivot_point_logprior

def log_likelihood(z:ArrayLike, obs:ArrayLike, eps:float=eps) -> float:
    """
    Returns the log-likelihood
    PARAMS:
    z : positions on the Euclidean plane
    obs : observed correlations (samples x edges)
    eps : offset for the normalization of d, and clipping of A
    """
    params = get_all_params(z, eps=eps)
    p = params['p']

    logprob_A = jstats.bernoulli.logpmf(obs, p).sum() # S x M obs --sum--> scalar logprob_A
    return logprob_A

def bookstein_log_likelihood(z:ArrayLike, obs:ArrayLike, eps:float=eps) -> float:
    """
    Returns the log-likelihood
    PARAMS:
    z : positions on Euclidean plane (N x D)
    obs : observed correlations (samples x edges)
    eps : offset for the normalization of d, and clipping of A
    """
    n_dims = z.shape[1]
    bookstein_anchors = get_bookstein_anchors(n_dims, bookstein_dist)

    # Concatenate bookstein targets to z
    zc = jnp.concatenate([bookstein_anchors, z])

    return log_likelihood(zc, obs, eps=eps)

def log_density(z:ArrayLike, obs:ArrayLike, mu:float=mu, sigma:float=sigma, eps:float=eps) -> float:
    """
    Returns the log-probability density of the observed edge weights under the Continuous Hyperbolic LSM.
    PARAMS:
    z : positions on Euclidean plane
    obs : observed correlations (samples x edges)
    mu : mean of the 2D Gaussian to sample _z
    sigma : standard deviation of the 2D Gaussian to sample _z
    eps : offset for the normalization of d, and clipping of A
    """
    prior_prob = log_prior(z, mu, sigma, sigma_T)
    likelihood_prob = log_likelihood(z, obs, eps=eps)
    return prior_prob + likelihood_prob

## SMC + Bookstein methods
def initialize_particles(key:PRNGKeyArray, num_particles:int, shape:tuple, mu:float=mu, sigma:float=sigma) -> Tuple[PRNGKeyArray, dict]:
    """
    Initializes the SMC particles. Equivalent to sample_prior, but with an extra dimension for the SMC particles.
    PARAMS:
    key : Random key for JAX functions
    num_particles : number of SMC particles
    shape : shape of the latent space positions
    mu : mean of the 2D Gaussian to sample p
    sigma : standard deviation of the 2D Gaussian to sample p
    """
    z_key, key = jax.random.split(key, 2)
    initial_position = {'z': sigma*jax.random.normal(z_key, shape=(num_particles, N, D))+mu}
    return key, initial_position

def initialize_bkst_particles(key:PRNGKeyArray, num_particles:int, shape:tuple, mu:float=mu, sigma:float=sigma) -> Tuple[PRNGKeyArray, dict]:
    """
    Initializes the SMC particles. Equivalent to sample_prior, but with an extra dimension for the SMC particles.
    PARAMS:
    key : Random key for JAX functions
    num_particles : number of SMC particles
    shape : shape of the latent space positions
    mu : mean of the 2D Gaussian to sample p
    sigma : standard deviation of the 2D Gaussian to sample p
    """
    N, D = shape
    z_key, key = jax.random.split(key, 2)
    initial_position = {'z': smc_bookstein_position(sigma * jax.random.normal(z_key, shape=(num_particles, N - D, D)) + mu)} # N-D to skip first D bkst nodes (they are implicit)
    return key, initial_position

def smc_bkst_inference_loop(key:PRNGKeyArray, smc_kernel:Callable, initial_state:ArrayLike) -> Tuple[PRNGKeyArray, int, float, TemperedSMCState]:
    """
    Run the temepered SMC algorithm with Bookstein anchoring.

    Run the adaptive algorithm until the tempering parameter lambda reaches the value lambda=1.
    PARAMS:
    key: random key for JAX functions
    smc_kernel: kernel for the SMC particles
    initial_state: beginning position of the algorithm
    """
    def cond(carry):
        state = carry[2]
        return state.lmbda < 1

    @jax.jit
    def step(carry):
        i, lml, s_values, state, key = carry
        key, subkey = jax.random.split(key)
        state, info = smc_kernel(subkey, state)
        lml += info.log_likelihood_increment
        return i+1, lml, state, key

    n_iter, lml, final_state, key = jax.lax.while_loop(
        cond, step, (0, 0., initial_state, key)
    )

    return key, n_iter, lml, final_state

def get_LSM_embedding(key:PRNGKeyArray, obs:ArrayLike, N:int = N, D:int = D, rmh_sigma:float = rmh_sigma, n_mcmc_steps:int = n_mcmc_steps, n_particles:int = n_particles) -> Tuple[PRNGKeyArray, float, TemperedSMCState]:
    """
    Creates a latent space embedding based on the given observations.
    Returns key,
    PARAMS:
    key: random key for JAX functions
    obs : (n_obs x M) upper triangles of the correlation matrices.
    N : number of nodes
    D : dimension of the latent space
    rmh_sigma : std of the within-SMC RMH sampler
    n_mcmc_steps : number of MCMC steps taken within each SMC iteration
    n_particles : number of SMC particles
    """
    # Define smc+bkst sampler
    _bookstein_log_prior = lambda state: bookstein_log_prior(**state)  # Parameters are taken from global parameters
    _bookstein_log_likelihood = lambda state: bookstein_log_likelihood(**state, obs=obs)  # Parameters are taken from global parameters

    rmh_parameters = {'sigma': rmh_sigma * jnp.eye((N - D) * D + 1)}
    smc = bjx.adaptive_tempered_smc(
        logprior_fn=_bookstein_log_prior,
        loglikelihood_fn=_bookstein_log_likelihood,
        mcmc_algorithm=bjx.rmh,
        mcmc_parameters=rmh_parameters,
        resampling_fn=resampling.systematic,
        target_ess=0.5,
        mcmc_iter=n_mcmc_steps,
    )

    # Initialize the particles
    key, init_position = initialize_bkst_particles(key, n_particles, (N, D))
    initial_smc_state = smc.init(init_position)

    # Run SMC inference
    key, n_iter, lml, states_rwm_smc = smc_bkst_inference_loop(key, smc.step, initial_smc_state)

    # Add Bookstein coordinates to SMC states
    states_rwm_smc = add_bkst_to_smc_trace(states_rwm_smc, bookstein_dist, D)

    return key, n_iter, lml, states_rwm_smc


if __name__ == "__main__":
    """
    Data is in a dictionary. The keys are defined by "S{n_sub}_{task}_{enc}", e.g. "S1_EMOTION_RL".
    The values per key are the upper triangle of the correlation matrix (length M list).
    We go through each subject/task, and take both encodings as seperate observations to create 1 embedding.
    """

    # Load labels
    if make_plot and label_location is not None:
        label_data = np.load(label_location)
        plt_labels = label_data[label_data.files[0]]
        if len(plt_labels) is not N:
            plt_labels = None
    else:
        plt_labels = None

    # Load data
    if not overwrite_data_filename:
        data_filename = get_filename_with_ext(base_data_filename, partial, bpf)
    else:
        data_filename = overwrite_data_filename
    obs, tasks, encs = load_observations(data_filename, task_filename, subject1, subjectn, M)

    for si, n_sub in enumerate(range(subject1, subjectn + 1)):
        for ti, task in enumerate(tasks):
            # Create LS embedding
            start_time = time.time()
            key, n_iter, lml, smc_embedding = get_LSM_embedding(key, obs[si, ti, :, :])  # Other parameters to get_LSM_embeddings are taken from globals.
            end_time = time.time()

            if do_print:
                print(f'Embedded S{n_sub}_{task} in {n_iter} iterations')

            # Save the statistics to the csv file
            if save_stats:
                stats_row = [f'S{n_sub}', task, n_particles, n_mcmc_steps, lml, end_time - start_time]
                with open(stats_filename, 'a', newline='') as f:
                    writer = csv.writer(f, delimiter=dl)
                    writer.writerow(stats_row)

            partial_txt = '_partial' if partial else ''
            base_save_filename = f"bin_euc_S{n_sub}_{task}_embedding{partial_txt}"

            if make_plot:
                z_positions = smc_embedding.particles['z']

                ## TODO: ADD LABELS!
                # Plot posterior
                plt.figure()
                ax = plt.gca()
                plot_posterior(z_positions,
                               edges=obs[si, ti, 0], # Dit is ook nog raar!
                               pos_labels=plt_labels,
                               ax=ax,
                               title=f"Proposal S{n_sub} {task}",
                               hyperbolic=False,
                               bkst=True,
                               threshold=plot_threshold
                               )
                poincare_disk = plt.Circle((0, 0), 1, color='k', fill=False, clip_on=False)
                ax.add_patch(poincare_disk)
                # Save figure
                savefile = get_filename_with_ext(base_save_filename, ext='png', folder=figure_folder)
                plt.savefig(savefile)
                plt.close()

            # Save data
            embedding_filename = get_filename_with_ext(base_save_filename, folder=output_folder)
            info_filename = get_filename_with_ext(f"bin_euc_S{n_sub}", ext='txt', folder=output_folder)
            with open(embedding_filename, 'wb') as f:
                pickle.dump(smc_embedding, f)
            with open(info_filename, 'a') as f:
                info_string = f'Task {task} took {end_time - start_time:.4f}sec ({n_iter} iterations) with lml={jnp.sum(lml):.4f}\n'
                f.write(info_string)

        # Add an empty line between each subject in the info file
        with open(info_filename, 'a') as f:
            f.write('\n')
    
    ## Save the new seed
    with open(seed_file, 'w') as f:
        f.write(str(key[1]))
    if do_print:
        print('Done')
