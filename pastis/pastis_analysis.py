"""
This is a module that lets you do a full PASTIS WFE requirement analysis from a PASTIS matrix.

Currently supports only LUVOIR.
"""
import os
import time
import numpy as np
from astropy.io import fits
import astropy.units as u
import logging
import matplotlib.pyplot as plt
import hcipy

from config import CONFIG_INI
from e2e_simulators.hicat_imaging import set_up_hicat
from e2e_simulators.luvoir_imaging import LuvoirAPLC
from matrix_building_numerical import calculate_unaberrated_contrast_and_normalization
import plotting as ppl
import util_pastis as util

log = logging.getLogger(__name__)


def modes_from_matrix(instrument, datadir, saving=True):
    """
    Calculate mode basis and singular values from PASTIS matrix using an SVD. In the case of the PASTIS matrix,
    this is equivalent to using an eigendecomposition, because the matrix is symmetric. Note how the SVD orders the
    modes and singular values in reverse order compared to an eigendecomposition.

    :param instrument: string, "LUVOIR" or "HiCAT"
    :param datadir: string, path to overall data directory containing matrix and results folder
    :param saving: string, whether to save singular values, modes and their plots or not; default=True
    :return: pastis modes (which are the singular vectors/eigenvectors), singular values/eigenvalues
    """

    # Read matrix
    matrix = fits.getdata(os.path.join(datadir, 'matrix_numerical', 'PASTISmatrix_num_piston_Noll1.fits'))

    # Get singular modes and values from SVD
    pmodes, svals, vh = np.linalg.svd(matrix, full_matrices=True)

    # Check for results directory and create if it doesn't exits
    if not os.path.isdir(os.path.join(datadir, 'results')):
        os.mkdir(os.path.join(datadir, 'results'))

    # Save singular values and pastis modes (singular vectors)
    if saving:
        np.savetxt(os.path.join(datadir, 'results', 'eigenvalues.txt'), svals)
        np.savetxt(os.path.join(datadir, 'results', 'pastis_modes.txt'), pmodes)

    # Plot singular values and save
    if saving:
        ppl.plot_eigenvalues(svals, nseg=svals.shape[0], wvln=CONFIG_INI.getfloat(instrument, 'lambda'),
                             out_dir=os.path.join(datadir, 'results'), save=True)

    return pmodes, svals


def modes_from_file(datadir):
    """
    Read mode basis and singular values of a PASTIS matrix from file.
    :param datadir: string, path to overall data directory containing matrix and results folder
    :return: pastis modes (which are the singular vectors/eigenvectors), singular values/eigenvalues
    """

    svals = np.loadtxt(os.path.join(datadir, 'results', 'eigenvalues.txt'))
    pmodes = np.loadtxt(os.path.join(datadir, 'results', 'pastis_modes.txt'))

    return pmodes, svals


def full_modes_from_themselves(instrument, pmodes, datadir, sim_instance, saving=False):
    """
    Put all modes onto the segmented mirror in the pupil and get full 2D pastis modes.

    Take the pmodes array of all modes (shape [segnum, modenum] = [nseg, nseg]) and apply them onto a segmented mirror
    in the pupil. This phase gets returned both as an array of hcipy.Fields, as well as a standard array of 2D arrays.
    Optionally, save a PDF displaying all modes, a fits cube and individual PDF images.

    :param instrument: string, 'LUVOIR' or 'HiCAT'
    :param pmodes: array of PASTIS modes [segnum, modenum], expected in nanometers
    :param datadir: string, path to overall data directory containing matrix and results folder
    :param sim_instance: class instance of the simulator for "instrument"
    :param saving: bool, whether to save figure to disk or not, default=False
    :return: mode_cube as array of 2D arrays (matplotlib)
    """

    nseg = pmodes.shape[0]
    seglist = util.get_segment_list(instrument)

    ### Put all modes sequentially on the segmented mirror and get them as a phase map, then convert to WFE map
    all_modes = []
    for i, thismode in enumerate(seglist):

        if instrument == "LUVOIR":
            log.info(f'Working on mode {thismode}/{nseg}.')
            wf_sm = util.apply_mode_to_luvoir(pmodes[:, i], sim_instance)
            all_modes.append((wf_sm.phase / wf_sm.wavenumber).shaped)   # wf_sm.phase is in rad, so this converts it to meters

        if instrument == 'HiCAT':
            log.info(f'Working on mode {thismode}/{nseg-1}.')
            for segnum in range(nseg):
                sim_instance.iris_dm.set_actuator(segnum, pmodes[segnum, i] / 1e9, 0, 0)   # /1e9 converts to meters
            psf, inter = sim_instance.calc_psf(return_intermediates=True)
            wf_sm = inter[1].phase

            hicat_wavenumber = 2 * np.pi / (CONFIG_INI.getfloat('HiCAT', 'lambda') / 1e9)   # /1e9 converts to meters
            all_modes.append(wf_sm / hicat_wavenumber)    # wf_sm is in rad, so this converts it to meters

    ### Check for results directory structure and create if it doesn't exist
    if saving:
        subdirs = [os.path.join(datadir, 'results'),
                   os.path.join(datadir, 'results', 'modes'),
                   os.path.join(datadir, 'results', 'modes', 'fits'),
                   os.path.join(datadir, 'results', 'modes', 'pdf')]
        for place in subdirs:
            if not os.path.isdir(place):
                os.mkdir(place)

    ### Plot all modes together and save
    if saving:
        log.info('Saving all PASTIS modes...')
        plt.figure(figsize=(36, 30))
        for i, thismode in enumerate(seglist):
            if instrument == 'LUVOIR':
                plt.subplot(12, 10, i + 1)
            if instrument == 'HiCAT':
                plt.subplot(8, 5, i + 1)
            plt.imshow(all_modes[i], cmap='RdBu')
            plt.axis('off')
            plt.title(f'Mode {thismode}')
        plt.savefig(os.path.join(datadir, 'results', 'modes', 'modes_piston.pdf'))

    ### Plot them individually and save as fits and pdf
    for i, thismode in enumerate(seglist):
        # pdf
        plt.clf()
        plt.imshow(all_modes[i], cmap='RdBu')    # TODO: this is now super slow for LUVOIR, using hcipy was way faster. Change back in LUVOIR case?
        plt.axis('off')
        plt.title(f'Mode {thismode}', size=30)
        if saving:
            plt.savefig(os.path.join(datadir, 'results', 'modes', 'pdf', f'mode_{thismode}.pdf'))

    # fits cube
    mode_cube = np.array(all_modes)
    if saving:
        hcipy.write_fits(mode_cube, os.path.join(datadir, 'results', 'modes', 'fits', 'cube_modes.fits'))

    return mode_cube


def full_modes_from_file(datadir):
    """
    Read all modes into an array of hcipy.Fields and an array of 2D arrays.
    :param datadir: string, path to overall data directory containing matrix and results folder
    :return: all_modes as array of Fields, mode_cube as array of 2D arrays (hcipy vs matplotlib)
    """

    mode_cube = hcipy.read_fits(os.path.join(datadir, 'results', 'modes', 'fits', 'cube_modes.fits'))
    all_modes = hcipy.Field(mode_cube.ravel())

    return all_modes, mode_cube


def calculate_sigma(cstat, nmodes, svalues, c_floor):
    """
    Calculate the maximum mode contribution(s) from the static contrast target and the singular values.
    :param cstat: float, static contrast requirement
    :param nmodes: int, number of contributing PASTIS modes we want to calculate the sigmas for
    :param svalues: float or array, singular value(s) of the mode(s) we are calculating the sigma(s) for
    :param c_floor: float, coronagraph floor (baseline contrast without aberrations)
    :return: sigma: float or array, maximum mode contribution sigma for each mode
    """
    sigma = np.sqrt((cstat - c_floor) / (nmodes * svalues))
    return sigma


def calculate_delta_sigma(cdyn, nmodes, svalue):
    """
    Calculate dynamic contrast contribution of a mode - not tested, not implemented anywhere
    :param cdyn: float, dynamic contrast requirement
    :param nseg: float, dynamic contrast requirement
    :param svalue: float, singular value of the mode we are calculating delta sigma for
    :return: float, dynamic contrast contribution
    """
    del_sigma = np.sqrt(cdyn / (np.sqrt(nmodes)*svalue))
    return del_sigma


def cumulative_contrast_e2e(instrument, pmodes, sigmas, sim_instance, dh_mask, norm_direct, individual=False):
    """
    Calculate the cumulative contrast or contrast per mode of a set of PASTIS modes with mode weights sigmas,
    using an E2E simulator.
    :param instrument: string, 'LUVOIR' or 'HiCAT'
    :param pmodes: array, PASTIS modes [nseg, nmodes]
    :param sigmas: array, weights per PASTIS mode
    :param sim_instance: class instance of the simulator for "instrument"
    :param dh_mask: hcipy.Field, dh_mask that goes together with the instance of the LUVOIR simulator
    :param norm_direct: float, normalization factor for PSF; peak of unaberrated direct PSF
    :param individual: bool, if False (default), calculates cumulative contrast, if True, calculates contrast per mode
    :return: cont_cum_e2e, list of cumulative or individual contrasts
    """

    cont_cum_e2e = []
    for maxmode in range(pmodes.shape[0]):

        if individual:
            opd = pmodes[:, maxmode] * sigmas[maxmode]
        else:
            opd = np.nansum(pmodes[:, :maxmode+1] * sigmas[:maxmode+1], axis=1)
        opd *= u.nm    # the package is currently set up to spit out the modes in units of nm

        if instrument == 'LUVOIR':
            sim_instance.flatten()
            for seg, val in enumerate(opd):
                sim_instance.set_segment(seg + 1, val.to(u.m).value/2, 0, 0)
            im_data = sim_instance.calc_psf()
            psf = im_data.shaped

        if instrument == 'HiCAT':
            sim_instance.iris_dm.flatten()
            for seg, val in enumerate(opd):
                sim_instance.iris_dm.set_actuator(seg, val.to(u.m).value, 0, 0)
            im_data = sim_instance.calc_psf()
            psf = im_data[0].data

        # Calculate the contrast from that PSF
        contrast = util.dh_mean(psf/norm_direct, dh_mask)
        cont_cum_e2e.append(contrast)

    return cont_cum_e2e


def cumulative_contrast_matrix(pmodes, sigmas, matrix, c_floor, individual=False):
    """
    Calculate the cumulative contrast or contrast per mode of a set of PASTIS modes with mode weights sigmas,
    using PASTIS propagation.
    :param pmodes: array, PASTIS modes [nseg, nmodes]
    :param sigmas: array, weights per PASTIS mode
    :param matrix: array, PASTIS matrix [nseg, nseg]
    :param c_floor: float, coronagraph contrast floor
    :param individual: bool, if False (default), calculates cumulative contrast, if True, calculates contrast per mode
    :return: cont_cum_pastis, list of cumulative or individual contrasts
    """
    cont_cum_pastis = []
    for maxmode in range(pmodes.shape[0]):

        if individual:
            aber = pmodes[:, maxmode] * sigmas[maxmode]
        else:
            aber = np.nansum(pmodes[:, :maxmode+1] * sigmas[:maxmode+1], axis=1)
        aber *= u.nm

        contrast_matrix = util.pastis_contrast(aber, matrix) + c_floor
        cont_cum_pastis.append(contrast_matrix)

    return cont_cum_pastis


def calculate_segment_constraints(pmodes, pastismatrix, c_target, coronagraph_floor):
    """
    Calculate segment-based PASTIS constraints from PASTIS matrix and PASTIS modes.
    :param pmodes: array, PASTIS modes [nseg, nmodes]
    :param pastismatrix: array, full PASTIS matrix [nseg, nseg]
    :param c_target: float, static target contrast
    :param coronagraph_floor: float, coronagraph contrast floor
    :return: mu_map: array, map of segment-based PASTIS constraints
    """
    nmodes = pmodes.shape[0]

    # Calculate the inverse of the pastis mode matrix
    modestosegs = np.linalg.pinv(pmodes)

    # Calculate all mean contrasts of the pastis modes directly (as-is, with natural normalization)
    c_avg = []
    for i in range(nmodes):
        c_avg.append(util.pastis_contrast(pmodes[:, i] * u.nm, pastismatrix) + coronagraph_floor)

    # Calculate segment requirements
    mu_map = np.sqrt(
        ((c_target - coronagraph_floor) / nmodes) / (np.dot(np.array(c_avg) - coronagraph_floor, np.square(modestosegs))))

    return mu_map


def calc_random_segment_configuration(instrument, sim_instance, mus, dh_mask, norm_direct):
    """
    Calculate the PSF after applying a randomly weighted set of segment-based PASTIS constraints on the pupil.
    :param instrument: str, "LUVOIR" or "HiCAT"
    :param sim_instance: class instance of the simulator for "instrument"
    :param mus: array, segment-based PASTIS constraints in nm
    :param dh_mask: hcipy.Field, dark hole mask for PSF produced by LuvoirAPLC instance
    :param norm_direct: float, normalization factor for PSF; peak of unaberrated direct PSF
    :return: random_map: list, random segment map used in this PSF calculation in m;
             rand_contrast: float, mean contrast of the calculated PSF
    """

    # Draw a normal distribution where the stddev gets scaled to mu later on
    segments_random_state = np.random.RandomState()
    rand = segments_random_state.normal(0, 1, mus.shape[0])

    random_map = []

    # Multiply each segment mu by one of these random numbers,
    # put that on the simulator and calculate the PSF and mean contrast.
    if instrument == "LUVOIR":
        sim_instance.flatten()
        for seg, (mu, randval) in enumerate(zip(mus, rand)):
            random_seg = mu * randval
            random_map.append(random_seg.to(u.m).value)
            sim_instance.set_segment(seg+1, random_seg.to(u.m).value/2, 0, 0)
        im_data = sim_instance.calc_psf()
        psf = im_data.shaped

    if instrument == 'HiCAT':
        sim_instance.iris_dm.flatten()
        for seg, (mu, randval) in enumerate(zip(mus, rand)):
            random_seg = mu * randval
            random_map.append(random_seg.to(u.m).value)
            sim_instance.iris_dm.set_actuator(seg, random_seg.to(u.m).value, 0, 0)
        im_data = sim_instance.calc_psf()
        psf = im_data[0].data

    rand_contrast = util.dh_mean(psf / norm_direct, dh_mask)

    return random_map, rand_contrast


def calc_random_mode_configurations(instrument, pmodes, sim_instance, sigmas, dh_mask, norm_direct):
    """
    Calculate the PSF after weighting the PASTIS modes with weights from a normal distribution with stddev = sigmas.
    :param instrument: str, "LUVOIR" or "HiCAT"
    :param pmodes: array, pastis mode matrix [nseg, nmodes]
    :param sim_instance: class instance of the simulator for "instrument"
    :param sigmas: array, mode-based PASTIS constraints
    :param dh_mask: hcipy.Field, dark hole mask for PSF produced by luvoir
    :param norm_direct: float, normalization factor for PSF; peak of unaberrated direct PSF
    :return: random_weights: array, random weights used in this PSF calculation
             rand_contrast: float, mean contrast of the calculated PSF
    """

    # Create a random number generator
    modes_random_state = np.random.RandomState()
    rand = modes_random_state.normal(0, 1, sigmas.shape[0])
    random_weights = sigmas * rand

    # Sum up all modes with randomly scaled sigmas to make total OPD
    opd = np.nansum(pmodes[:, :] * random_weights, axis=1)
    opd *= u.nm

    # Apply random aberration to E2E simulator
    if instrument == "LUVOIR":
        sim_instance.flatten()
        for seg, aber in enumerate(opd):
            sim_instance.set_segment(seg + 1, aber.to(u.m).value / 2, 0, 0)
        im_data = sim_instance.calc_psf()
        psf = im_data.shaped

    if instrument == 'HiCAT':
        sim_instance.iris_dm.flatten()
        for seg, aber in enumerate(opd):
            sim_instance.iris_dm.set_actuator(seg, aber.to(u.m).value, 0, 0)
        im_data = sim_instance.calc_psf()
        psf = im_data[0].data

    rand_contrast = util.dh_mean(psf / norm_direct, dh_mask)

    return random_weights, rand_contrast


def run_full_pastis_analysis(instrument, run_choice, design=None, c_target=1e-10, n_repeat=100):
    """
    Run a full PASTIS analysis on a given PASTIS matrix.

    The first couple of lines contain switches to turn different parts of the analysis on and off. These include:
    1. calculating the PASTIS modes
    2. calculating the PASTIS mode weights sigma under assumption of a uniform contrast allocation across all modes
    3. running an E2E Monte Carlo simulation on the modes with their weights sigma from the uniform contrast allocation
    4. calculating a cumulative contrast plot from the sigmas of the uniform contrast allocation
    5. calculating the segment constraints mu under assumption of uniform statistical contrast contribution across segments
    6. running an E2E Monte Carlo simulation on the segments with their weights mu
    7. calculating the segment- and mode-space covariance matrices Ca and Cb
    8. analytically calculating the statistical mean contrast and its variance
    9. calculting segment-based error budget

    :param instrument: str, "LUVOIR" or "HiCAT"
    :param run_choice: str, path to data and where outputs will be saved
    :param design: str, optional, default=None, which means we read from the configfile: what coronagraph design
               to use - 'small', 'medium' or 'large'
    :param c_target: float, target contrast
    :param n_repeat: number of realizations in both Monte Carlo simulations (modes and segments), default=100
    """

    # Which parts are we running?
    calculate_modes = True
    calculate_sigmas = True
    run_monte_carlo_modes = True
    calc_cumulative_contrast = True
    calculate_mus = True
    run_monte_carlo_segments = True
    calculate_covariance_matrices = True
    analytical_statistics = True
    calculate_segment_based = True

    # Data directory
    workdir = os.path.join(CONFIG_INI.get('local', 'local_data_path'), run_choice)

    nseg = CONFIG_INI.getint(instrument, 'nb_subapertures')
    wvln = CONFIG_INI.getfloat(instrument, 'lambda') * 1e-9   # [m]

    log.info('Setting up optics...')
    log.info(f'Data folder: {workdir}')
    log.info(f'Instrument: {instrument}')

    # Set up simulator, calculate reference PSF and dark hole mask
    # TODO: replace this section with calculate_unaberrated_contrast_and_normalization(). This will require to save out
    # reference and unaberrated coronagraphic PSF already in matrix generation.
    if instrument == "LUVOIR":
        if design is None:
            design = CONFIG_INI.get('LUVOIR', 'coronagraph_design')
            log.info(f'Coronagraph design: {design}')

        sampling = CONFIG_INI.getfloat('LUVOIR', 'sampling')
        optics_input = CONFIG_INI.get('LUVOIR', 'optics_path')
        luvoir = LuvoirAPLC(optics_input, design, sampling)

        # Generate reference PSF and unaberrated coronagraphic image
        luvoir.flatten()
        psf_unaber, ref = luvoir.calc_psf(ref=True, display_intermediate=False)
        norm = ref.max()

        psf_unaber = psf_unaber.shaped / norm
        dh_mask = luvoir.dh_mask.shaped
        sim_instance = luvoir

    if instrument == 'HiCAT':
        hicat_sim = set_up_hicat(apply_continuous_dm_maps=True)

        # Generate reference PSF and unaberrated coronagraphic image
        hicat_sim.include_fpm = False
        direct = hicat_sim.calc_psf()
        norm = direct[0].data.max()

        hicat_sim.include_fpm = True
        coro_image = hicat_sim.calc_psf()
        psf_unaber = coro_image[0].data / norm

        # Create DH mask
        iwa = CONFIG_INI.getfloat('HiCAT', 'IWA')
        owa = CONFIG_INI.getfloat('HiCAT', 'OWA')
        sampling = CONFIG_INI.getfloat('HiCAT', 'sampling')
        dh_mask = util.create_dark_hole(psf_unaber, iwa, owa, sampling).astype('bool')

        sim_instance = hicat_sim

    # TODO: this would also be part of the refactor mentioned above
    # Calculate coronagraph contrast floor
    coro_floor = util.dh_mean(psf_unaber, dh_mask)
    log.info(f'Coronagraph floor: {coro_floor}')

    # Read the PASTIS matrix
    matrix = fits.getdata(os.path.join(workdir, 'matrix_numerical', 'PASTISmatrix_num_piston_Noll1.fits'))

    ### Calculate PASTIS modes and singular values/eigenvalues
    if calculate_modes:
        log.info('Calculating all PASTIS modes')
        pmodes, svals = modes_from_matrix(instrument, workdir)

        ### Get full 2D modes and save them
        mode_cube = full_modes_from_themselves(instrument, pmodes, workdir, sim_instance, saving=True)

    else:
        log.info(f'Reading PASTIS modes from {workdir}')
        pmodes, svals = modes_from_file(workdir)

    ### Calculate mode-based static constraints
    if calculate_sigmas:
        log.info('Calculating static sigmas')
        sigmas = calculate_sigma(c_target, nseg, svals, coro_floor)
        np.savetxt(os.path.join(workdir, 'results', f'mode_requirements_{c_target}_uniform.txt'), sigmas)

        # Plot static mode constraints
        ppl.plot_mode_weights_simple(sigmas, wvln,
                                     out_dir=os.path.join(workdir, 'results'),
                                     c_target=c_target,
                                     fname_suffix='uniform',
                                     save=True)

    else:
        log.info(f'Reading sigmas from {workdir}')
        sigmas = np.loadtxt(os.path.join(workdir, 'results', f'mode_requirements_{c_target}_uniform.txt'))

    ### Calculate Monte Carlo simulation for sigmas, with E2E
    if run_monte_carlo_modes:
        log.info('\nRunning Monte Carlo simulation for modes')
        # Keep track of time
        start_monte_carlo_modes = time.time()

        all_contr_rand_modes = []
        all_random_weight_sets = []
        for rep in range(n_repeat):
            log.info(f'Mode realization {rep + 1}/{n_repeat}')
            random_weights, one_contrast_mode = calc_random_mode_configurations(instrument, pmodes, sim_instance, sigmas, dh_mask, norm)
            all_random_weight_sets.append(random_weights)
            all_contr_rand_modes.append(one_contrast_mode)

        # Empirical mean and standard deviation of the distribution
        mean_modes = np.mean(all_contr_rand_modes)
        stddev_modes = np.std(all_contr_rand_modes)
        log.info(f'Mean of the Monte Carlo result modes: {mean_modes}')
        log.info(f'Standard deviation of the Monte Carlo result modes: {stddev_modes}')
        end_monte_carlo_modes = time.time()

        # Save Monte Carlo simulation
        np.savetxt(os.path.join(workdir, 'results', f'mc_mode_reqs_{c_target}.txt'), all_random_weight_sets)
        np.savetxt(os.path.join(workdir, 'results', f'mc_modes_contrasts_{c_target}.txt'), all_contr_rand_modes)

        ppl.plot_monte_carlo_simulation(all_contr_rand_modes, out_dir=os.path.join(workdir, 'results'),
                                        c_target=c_target, segments=False, stddev=stddev_modes,
                                        save=True)

    ###  Calculate cumulative contrast plot with E2E simulator and matrix product
    if calc_cumulative_contrast:
        log.info('Calculating cumulative contrast plot, uniform contrast across all modes')
        cumulative_e2e = cumulative_contrast_e2e(instrument, pmodes, sigmas, sim_instance, dh_mask, norm)
        cumulative_pastis = cumulative_contrast_matrix(pmodes, sigmas, matrix, coro_floor)

        np.savetxt(os.path.join(workdir, 'results', f'cumul_contrast_accuracy_e2e_{c_target}.txt'), cumulative_e2e)
        np.savetxt(os.path.join(workdir, 'results', f'cumul_contrast_accuracy_pastis_{c_target}.txt'), cumulative_pastis)

        # Plot the cumulative contrast from E2E simulator and matrix
        ppl.plot_cumulative_contrast_compare_accuracy(cumulative_pastis, cumulative_e2e,
                                                      out_dir=os.path.join(workdir, 'results'),
                                                      c_target=c_target,
                                                      save=True)

    else:
        log.info('Loading uniform cumulative contrast from disk.')
        cumulative_e2e = np.loadtxt(os.path.join(workdir, 'results', f'cumul_contrast_accuracy_e2e_{c_target}.txt'))

    ### Calculate segment-based static constraints
    if calculate_mus:
        log.info('Calculating segment-based constraints')
        mus = calculate_segment_constraints(pmodes, matrix, c_target, coro_floor)
        np.savetxt(os.path.join(workdir, 'results', f'segment_requirements_{c_target}.txt'), mus)

        ppl.plot_segment_weights(mus, out_dir=os.path.join(workdir, 'results'), c_target=c_target, save=True)
        ppl.plot_mu_map(instrument, mus, sim_instance, out_dir=os.path.join(workdir, 'results'), design=design, c_target=c_target, save=True)

        # Apply mu map directly and run through E2E simulator
        mus *= u.nm

        if instrument == 'LUVOIR':
            sim_instance.flatten()
            for seg, mu in enumerate(mus):
                sim_instance.set_segment(seg + 1, mu.to(u.m).value / 2, 0, 0)
            im_data = sim_instance.calc_psf()
            psf_pure_mu_map = im_data.shaped
        if instrument == 'HiCAT':
            sim_instance.iris_dm.flatten()
            for seg, mu in enumerate(mus):
                sim_instance.iris_dm.set_actuator(seg, mu / 1e9, 0, 0)  # /1e9 converts to meters
            im_data = sim_instance.calc_psf()
            psf_pure_mu_map = im_data[0].data

        contrast_mu = util.dh_mean(psf_pure_mu_map / norm, dh_mask)
        log.info(f'Contrast with pure mu-map: {contrast_mu}')

    else:
        log.info(f'Reading mus from {workdir}')
        mus = np.loadtxt(os.path.join(workdir, 'results', f'segment_requirements_{c_target}.txt'))
        mus *= u.nm

    ### Calculate Monte Carlo confirmation for segments, with E2E
    if run_monte_carlo_segments:
        log.info('\nRunning Monte Carlo simulation for segments')
        # Keep track of time
        start_monte_carlo_seg = time.time()

        all_contr_rand_seg = []
        all_random_maps = []
        for rep in range(n_repeat):
            log.info(f'Segment realization {rep + 1}/{n_repeat}')
            random_map, one_contrast_seg = calc_random_segment_configuration(instrument, sim_instance, mus, dh_mask, norm)
            all_random_maps.append(random_map)
            all_contr_rand_seg.append(one_contrast_seg)

        # Empirical mean and standard deviation of the distribution
        mean_segments = np.mean(all_contr_rand_seg)
        stddev_segments = np.std(all_contr_rand_seg)
        log.info(f'Mean of the Monte Carlo result segments: {mean_segments}')
        log.info(f'Standard deviation of the Monte Carlo result segments: {stddev_segments}')
        with open(os.path.join(workdir, 'results', f'statistical_contrast_empirical_{c_target}.txt'), 'w') as file:
            file.write(f'Empirical, statistical mean: {mean_segments}')
            file.write(f'\nEmpirical variance: {stddev_segments**2}')
        end_monte_carlo_seg = time.time()

        log.info('\nRuntimes:')
        log.info('Monte Carlo on segments with {} iterations: {} sec = {} min = {} h'.format(n_repeat, end_monte_carlo_seg - start_monte_carlo_seg,
                                                                                          (end_monte_carlo_seg - start_monte_carlo_seg) / 60,
                                                                                          (end_monte_carlo_seg - start_monte_carlo_seg) / 3600))

        # Save Monte Carlo simulation
        np.savetxt(os.path.join(workdir, 'results', f'mc_segment_req_maps_{c_target}.txt'), all_random_maps)   # in m
        np.savetxt(os.path.join(workdir, 'results', f'mc_segments_contrasts_{c_target}.txt'), all_contr_rand_seg)

        ppl.plot_monte_carlo_simulation(all_contr_rand_seg, out_dir=os.path.join(workdir, 'results'),
                                        c_target=c_target, segments=True, stddev=stddev_segments,
                                        save=True)

    ### Calculate covariance matrices
    if calculate_covariance_matrices:
        log.info('Calculating covariance matrices')
        Ca = np.diag(np.square(mus))
        hcipy.write_fits(Ca, os.path.join(workdir, 'results', f'cov_matrix_segments_Ca_{c_target}_segment-based.fits'))

        Cb = np.dot(np.transpose(pmodes), np.dot(Ca, pmodes))
        hcipy.write_fits(Cb, os.path.join(workdir, 'results', f'cov_matrix_modes_Cb_{c_target}_segment-based.fits'))

        ppl.plot_covariance_matrix(Ca, os.path.join(workdir, 'results'), c_target, segment_space=True,
                                   fname_suffix='segment-based', save=True)
        ppl.plot_covariance_matrix(Cb, os.path.join(workdir, 'results'), c_target, segment_space=False,
                                   fname_suffix='segment-based', save=True)

    else:
        log.info('Loading covariance matrices from disk.')
        Ca = fits.getdata(os.path.join(workdir, 'results', f'cov_matrix_segments_Ca_{c_target}_segment-based.fits'))
        Cb = fits.getdata(os.path.join(workdir, 'results', f'cov_matrix_modes_Cb_{c_target}_segment-based.fits'))

    ### Analytically calculate statistical mean contrast and its variance
    if analytical_statistics:
        log.info('Calculating analytical statistics.')
        mean_stat_c = util.calc_statistical_mean_contrast(matrix, Ca, coro_floor)
        var_c = util.calc_variance_of_mean_contrast(matrix, Ca)
        log.info(f'Analytical statistical mean: {mean_stat_c}')
        log.info(f'Analytical standard deviation: {var_c}')

        with open(os.path.join(workdir, 'results', f'statistical_contrast_analytical_{c_target}.txt'), 'w') as file:
            file.write(f'Analytical, statistical mean: {mean_stat_c}')
            file.write(f'\nAnalytical variance: {var_c}')

    ### Calculate segment-based error budget
    if calculate_segment_based:
        log.info('Calculating segment-based error budget.')

        # Extract segment-based mode weights
        log.info('Calculate segment-based mode weights')
        sigmas_opt = np.sqrt(np.diag(Cb))
        np.savetxt(os.path.join(workdir, 'results', f'mode_requirements_{c_target}_segment-based.txt'), sigmas_opt)
        ppl.plot_mode_weights_simple(sigmas_opt, wvln, out_dir=os.path.join(workdir, 'results'), c_target=c_target,
                                     fname_suffix='segment-based', save=True)
        ppl.plot_mode_weights_double_axis((sigmas, sigmas_opt), wvln, os.path.join(workdir, 'results'), c_target,
                                          fname_suffix='segment-based-vs-uniform',
                                          labels=('Uniform error budget', 'Segment-based error budget'),
                                          alphas=(0.5, 1.), linestyles=('--', '-'), colors=('k', 'r'), save=True)

        # Calculate contrast per mode
        log.info('Calculating contrast per mode')
        per_mode_opt_e2e = cumulative_contrast_e2e(instrument, pmodes, sigmas_opt, sim_instance, dh_mask, norm, individual=True)
        np.savetxt(os.path.join(workdir, 'results', f'contrast_per_mode_{c_target}_e2e_segment-based.txt'),
                   per_mode_opt_e2e)
        ppl.plot_contrast_per_mode(per_mode_opt_e2e, coro_floor, c_target, pmodes.shape[0],
                                   os.path.join(workdir, 'results'), save=True)

        # Calculate segment-based cumulative contrast
        log.info('Calculating segment-based cumulative contrast')
        cumulative_opt_e2e = cumulative_contrast_e2e(instrument, pmodes, sigmas_opt, sim_instance, dh_mask, norm)
        np.savetxt(os.path.join(workdir, 'results', f'cumul_contrast_allocation_e2e_{c_target}_segment-based.txt'),
                   cumulative_opt_e2e)

        # Plot cumulative contrast from E2E simulator, segment-based vs. uniform error budget
        ppl.plot_cumulative_contrast_compare_allocation(cumulative_opt_e2e, cumulative_e2e, os.path.join(workdir, 'results'),
                                                        c_target, fname_suffix='segment-based-vs-uniform', save=True)

    ### DONE
    log.info(f"All saved in {os.path.join(workdir, 'results')}")
    log.info('Good job')


if __name__ == '__main__':

    instrument = CONFIG_INI.get('telescope', 'name')
    run = CONFIG_INI.get('numerical', 'current_analysis')
    c_target = 1e-10
    mc_repeat = 100

    run_full_pastis_analysis(instrument, run_choice=run, c_target=c_target, n_repeat=mc_repeat)
