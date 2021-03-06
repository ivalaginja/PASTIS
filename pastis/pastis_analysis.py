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
from matplotlib.colors import LogNorm
import hcipy as hc
from hcipy.optics.segmented_mirror import SegmentedMirror

from config import CONFIG_INI
from e2e_simulators.luvoir_imaging import LuvoirAPLC
import plotting as ppl
import util_pastis as util

log = logging.getLogger(__name__)


def modes_from_matrix(datadir, saving=True):
    """
    Calculate mode basis and singular values from PASTIS matrix using an SVD. In the case of the PASTIS matrix,
    this is equivalent to using an eigendecomposition, because the matrix is symmetric. Note how the SVD orders the
    modes and singular values in reverse order conpared to an eigendecomposition.
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

    # Save singular values and modes (singular vectors)
    if saving:
        np.savetxt(os.path.join(datadir, 'results', 'eigenvalues.txt'), svals)
        np.savetxt(os.path.join(datadir, 'results', 'pastis_modes.txt'), pmodes)

    # Plot singular values and save
    if saving:
        ppl.plot_eigenvalues(svals, nseg=svals.shape[0], wvln=CONFIG_INI.getfloat('LUVOIR', 'lambda'),
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


def full_modes_from_themselves(pmodes, datadir, sm, wf_aper, saving=False):
    """
    Put all modes onto the segmented mirror in the pupil and get full 2D pastis modes.

    Take the pmodes array of all modes (shape [segnum, modenum] = [nseg, nseg]) and apply them onto a segmented mirror
    in the pupil. This phase gets returned both as an array of hcipy.Fields, as well as a standard array of 2D arrays.
    Optionally, save a PDF displaying all modes, a fits cube and individual PDF images.
    :param pmodes: array of PASTIS modes [segnum, modenum]
    :param datadir: string, path to overall data directory containing matrix and results folder
    :param saving: bool, whether to save figure to disk or not, default=False
    :return: all_modes as array of Fields, mode_cube as array of 2D arrays (hcipy vs matplotlib)
    """

    nseg = pmodes.shape[0]

    ### Put all modes sequentially on the segmented mirror and get them as a phase map, then convert to WFE map
    all_modes = []
    for thismode in range(nseg):
        log.info(f'Working on mode {thismode + 1}/{nseg}.')

        wf_sm = apply_mode_to_sm(pmodes[:, thismode], sm, wf_aper)
        all_modes.append(wf_sm.phase / wf_sm.wavenumber)    # wf.phase is in rad, so this converts it to meters

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
        for thismode in range(nseg):
            plt.subplot(12, 10, thismode + 1)
            hc.imshow_field(all_modes[thismode], cmap='RdBu')
            plt.axis('off')
            plt.title(f'Mode {thismode + 1}')
        plt.savefig(os.path.join(datadir, 'results', 'modes', 'modes_piston.pdf'))

    ### Plot them individually and save as fits and pdf
    mode_cube = []  # to save as a fits cube
    for thismode in range(nseg):

        # pdf
        plt.clf()
        hc.imshow_field(all_modes[thismode], cmap='RdBu')
        plt.axis('off')
        plt.title(f'Mode {thismode + 1}', size=30)
        if saving:
            plt.savefig(os.path.join(datadir, 'results', 'modes', 'pdf', f'mode_{thismode+1}.pdf'))

        # for the fits cube
        mode_cube.append(all_modes[thismode].shaped)

    # fits cube
    mode_cube = np.array(mode_cube)
    if saving:
        hc.write_fits(mode_cube, os.path.join(datadir, 'results', 'modes', 'fits', 'cube_modes.fits'))

    return all_modes, mode_cube


def apply_mode_to_sm(pmode, sm, wf_aper):
    """
    Apply a PASTIS mode to the segmented mirror (SM) and return the propagated wavefront "through" the SM.

    This function first flattens the segmented mirror and then applies all segment coefficients from the input mode
    one by one to the segmented mirror.
    :param pmode: array, a single PASTIS mode [nseg] or any other segment phase map in NANOMETERS
    :param sm: hcipy.SegmentedMirror
    :param wf_aper: hcipy.Wavefront of the aperture
    :return: wf_sm: hcipy.Wavefront of the segmented mirror propagation
    """

    # Flatten SM to be sure we have no residual aberrations
    sm.flatten()

    # Loop through all segments to put them on the segmented mirror one by one
    for seg, val in enumerate(pmode):
        val *= u.nm  # the LUVOIR modes come out in units of nanometers
        sm.set_segment(seg + 1, val.to(u.m).value / 2, 0, 0)  # /2 because this SM works in surface, not OPD

    # Propagate the aperture wavefront through the SM
    wf_sm = sm(wf_aper)

    return wf_sm


def full_modes_from_file(datadir):
    """
    Read all modes into an array of hcipy.Fields and an array of 2D arrays.
    :param datadir: string, path to overall data directory containing matrix and results folder
    :return: all_modes as array of Fields, mode_cube as array of 2D arrays (hcipy vs matplotlib)
    """

    mode_cube = hc.read_fits(os.path.join(datadir, 'results', 'modes', 'fits', 'cube_modes.fits'))
    all_modes = hc.Field(mode_cube.ravel())

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


def cumulative_contrast_e2e(pmodes, sigmas, luvoir, dh_mask, individual=False):
    """
    Calculate the cumulative contrast or contrast per mode of a set of PASTIS modes with mode weights sigmas,
    using an E2E simulator.
    :param pmodes: array, PASTIS modes [nseg, nmodes]
    :param sigmas: array, weights per PASTIS mode
    :param luvoir: LuvoirAPLC
    :param dh_mask: hcipy.Field, dh_mask that goes together with the instance of the LUVOIR simulator
    :param individual: bool, if False (default), calculates cumulative contrast, if True, calculates contrast per mode
    :return: cont_cum_e2e, list of cumulative or individual contrasts
    """

    cont_cum_e2e = []
    for maxmode in range(pmodes.shape[0]):

        if individual:
            opd = pmodes[:, maxmode] * sigmas[maxmode]
        else:
            opd = np.nansum(pmodes[:, :maxmode+1] * sigmas[:maxmode+1], axis=1)

        luvoir.flatten()
        for seg, val in enumerate(opd):
            val *= u.nm    # the LUVOIR modes come out in units of nanometers
            luvoir.set_segment(seg + 1, val.to(u.m).value/2, 0, 0)

        # Get PSF from putting this WFE on the simulator
        psf, ref = luvoir.calc_psf(ref=True)
        norm = ref.max()

        # Calculate the contrast from that PSF
        contrast = util.dh_mean(psf/norm, dh_mask)
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
        ((c_target - coronagraph_floor) / nmodes) / (np.dot(c_avg - coronagraph_floor, np.square(modestosegs))))

    return mu_map


def calc_random_segment_configuration(luvoir, mus, dh_mask):
    """
    Calculate the PSF after applying a randomly weighted set of segment-based PASTIS constraints on the pupil.
    :param luvoir: LuvoirAPLC
    :param mus: array, segment-based PASTIS constraints in nm
    :param dh_mask: hcipy.Field, dark hole mask for PSF produced by LuvoirAPLC instance
    :return: random_map: list, random segment map used in this PSF calculation in m;
             rand_contrast: float, mean contrast of the calculated PSF
    """

    # Draw a normal distribution where the stddev gets scaled to mu later on
    rand = np.random.normal(0, 1, mus.shape[0])

    mus *= u.nm

    # Multiply each segment mu by one of these random numbers,
    # put that on the LUVOIR SM and calculate the PSF.
    luvoir.flatten()
    random_map = []
    for seg, (mu, randval) in enumerate(zip(mus, rand)):
        random_seg = mu * randval
        random_map.append(random_seg.to(u.m).value)
        luvoir.set_segment(seg+1, (random_seg).to(u.m).value/2, 0, 0)
    psf, ref = luvoir.calc_psf(ref=True, display_intermediate=False)

    # plt.figure()
    # plt.subplot(1, 3, 1)
    # hc.imshow_field(dh_mask)
    # plt.subplot(1, 3, 2)
    # hc.imshow_field(psf, norm=LogNorm(), mask=dh_mask)
    # plt.subplot(1, 3, 3)
    # hc.imshow_field(psf, norm=LogNorm())
    # plt.show()

    rand_contrast = util.dh_mean(psf / ref.max(), dh_mask)

    return random_map, rand_contrast


def calc_random_mode_configurations(pmodes, luvoir, sigmas, dh_mask):
    """
    Calculate the PSF after weighting the PASTIS modes with weights from a normal distribution with stddev = sigmas.
    :param pmodes: array, pastis mode matrix [nseg, nmodes]
    :param luvoir: LuvoirAPLC
    :param sigmas: array, mode-based PASTIS constraints
    :param dh_mask: hcipy.Field, dark hole mask for PSF produced by luvoir
    :return: random_weights: array, random weights used in this PSF calculation
             rand_contrast: float, mean contrast of the calculated PSF
    """

    # Create normal distribution
    rand = np.random.normal(0, 1, sigmas.shape[0])
    random_weights = sigmas * rand

    # Sum up all modes with randomly scaled sigmas to make total OPD
    opd = np.nansum(pmodes[:, :] * random_weights, axis=1)
    opd *= u.nm

    luvoir.flatten()
    for seg, aber in enumerate(opd):
        luvoir.set_segment(seg + 1, aber.to(u.m).value / 2, 0, 0)
    psf, ref = luvoir.calc_psf(ref=True, display_intermediate=False)

    rand_contrast = util.dh_mean(psf / ref.max(), dh_mask)

    return random_weights, rand_contrast


def run_full_pastis_analysis_luvoir(design, run_choice, c_target=1e-10, n_repeat=100):
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

    :param design: str, "small", "medium" or "large" LUVOIR-A APLC design
    :param run_choice: str, path to data and where outputs will be saved
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

    # LUVOIR coronagraph parameters
    sampling = CONFIG_INI.getfloat('numerical', 'sampling')

    nseg = CONFIG_INI.getint('LUVOIR', 'nb_subapertures')
    wvln = CONFIG_INI.getfloat('LUVOIR', 'lambda') * 1e-9   # [m]

    log.info('Setting up optics...')
    log.info(f'Data folder: {workdir}')
    log.info(f'Coronagraph: {design}')

    # Create SM
    # Read pupil and indexed pupil
    inputdir = CONFIG_INI.get('LUVOIR', 'optics_path')
    aper_path = 'inputs/TelAp_LUVOIR_gap_pad01_bw_ovsamp04_N1000.fits'
    aper_ind_path = 'inputs/TelAp_LUVOIR_gap_pad01_bw_ovsamp04_N1000_indexed.fits'
    aper_read = hc.read_fits(os.path.join(inputdir, aper_path))
    aper_ind_read = hc.read_fits(os.path.join(inputdir, aper_ind_path))

    # Sample them on a pupil grid and make them hc.Fields
    pupil_grid = hc.make_pupil_grid(dims=aper_ind_read.shape[0], diameter=15)
    aper = hc.Field(aper_read.ravel(), pupil_grid)
    aper_ind = hc.Field(aper_ind_read.ravel(), pupil_grid)

    # Create the wavefront on the aperture
    wf_aper = hc.Wavefront(aper, wvln)

    # Load segment positions from fits header
    hdr = fits.getheader(os.path.join(inputdir, aper_ind_path))
    poslist = []
    for i in range(nseg):
        segname = 'SEG' + str(i + 1)
        xin = hdr[segname + '_X']
        yin = hdr[segname + '_Y']
        poslist.append((xin, yin))
    poslist = np.transpose(np.array(poslist))
    seg_pos = hc.CartesianGrid(poslist)

    # Instantiate segmented mirror
    sm = SegmentedMirror(aper_ind, seg_pos)

    # Instantiate LUVOIR
    optics_input = CONFIG_INI.get('LUVOIR', 'optics_path')
    luvoir = LuvoirAPLC(optics_input, design, sampling)

    # Generate reference PSF and coronagraph contrast floor
    luvoir.flatten()
    psf_unaber, ref = luvoir.calc_psf(ref=True, display_intermediate=False)
    norm = ref.max()

    plt.figure()
    plt.subplot(1, 3, 1)
    plt.title("Dark hole mask")
    hc.imshow_field(luvoir.dh_mask)
    plt.subplot(1, 3, 2)
    plt.title("Unaberrated PSF")
    hc.imshow_field(psf_unaber, norm=LogNorm(), mask=luvoir.dh_mask)
    plt.subplot(1, 3, 3)
    plt.title("Unaberrated PSF (masked)")
    hc.imshow_field(psf_unaber, norm=LogNorm())
    plt.savefig(os.path.join(workdir, 'unaberrated_dh.pdf'))

    # Calculate coronagraph floor
    coro_floor = util.dh_mean(psf_unaber/norm, luvoir.dh_mask)
    log.info(f'Coronagraph floor: {coro_floor}')
    with open(os.path.join(workdir, 'coronagraph_floor.txt'), 'w') as file:
        file.write(f'{coro_floor}')

    # Read the PASTIS matrix
    matrix = fits.getdata(os.path.join(workdir, 'matrix_numerical', 'PASTISmatrix_num_piston_Noll1.fits'))

    ### Calculate PASTIS modes and singular values/eigenvalues
    if calculate_modes:
        log.info('Calculating all PASTIS modes')
        pmodes, svals = modes_from_matrix(workdir)

        ### Get full 2D modes and save them
        all_modes, mode_cube = full_modes_from_themselves(pmodes, workdir, sm, wf_aper, saving=True)

    else:
        log.info(f'Reading PASTIS modes from {workdir}')
        pmodes, svals = modes_from_file(workdir)

    ### Calculate mode-based static constraints
    if calculate_sigmas:
        log.info('Calculating static sigmas')
        sigmas = calculate_sigma(c_target, nseg, svals, coro_floor)
        np.savetxt(os.path.join(workdir, 'results', f'mode_requirements_{c_target}_uniform.txt'), sigmas)

        # Plot static mode constraints
        ppl.plot_mode_weights_simple(sigmas, wvln=CONFIG_INI.getfloat('LUVOIR', 'lambda'),
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
            random_weights, one_contrast_mode = calc_random_mode_configurations(pmodes, luvoir, sigmas, luvoir.dh_mask)
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
        cumulative_e2e = cumulative_contrast_e2e(pmodes, sigmas, luvoir, luvoir.dh_mask)
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

        # Put mus on SM and plot
        wf_constraints = apply_mode_to_sm(mus, sm, wf_aper)

        ppl.plot_segment_weights(mus, out_dir=os.path.join(workdir, 'results'), c_target=c_target, save=True)
        ppl.plot_mu_map(mus, wvln=CONFIG_INI.getfloat('LUVOIR', 'lambda'), out_dir=os.path.join(workdir, 'results'),
                        design=design, c_target=c_target, save=True)
    else:
        log.info(f'Reading mus from {workdir}')
        mus = np.loadtxt(os.path.join(workdir, 'results', f'segment_requirements_{c_target}.txt'))

    ### Calculate Monte Carlo confirmation for segments, with E2E
    if run_monte_carlo_segments:
        log.info('\nRunning Monte Carlo simulation for segments')
        # Keep track of time
        start_monte_carlo_seg = time.time()

        all_contr_rand_seg = []
        all_random_maps = []
        for rep in range(n_repeat):
            log.info(f'Segment realization {rep + 1}/{n_repeat}')
            random_map, one_contrast_seg = calc_random_segment_configuration(luvoir, mus, luvoir.dh_mask)
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
        hc.write_fits(Ca, os.path.join(workdir, 'results', f'cov_matrix_segments_Ca_{c_target}_segment-based.fits'))

        Cb = np.dot(np.transpose(pmodes), np.dot(Ca, pmodes))
        hc.write_fits(Cb, os.path.join(workdir, 'results', f'cov_matrix_modes_Cb_{c_target}_segment-based.fits'))

        ppl.plot_covariance_matrix(Ca, os.path.join(workdir, 'results'), c_target, segment_space=True,
                                   fname_suffix='segment-based', save=True)
        ppl.plot_covariance_matrix(Cb, os.path.join(workdir, 'results'), c_target, segment_space=False,
                                   fname_suffix='segment-based', save=True)

    else:
        log.info('Loading covariance matrices from disk.')
        Ca = fits.getdata(os.path.join(workdir, 'results', f'cov_matrix_segments_Ca_{c_target}.fits'))
        Cb = fits.getdata(os.path.join(workdir, 'results', f'cov_matrix_modes_Cb_{c_target}.fits'))

    ### Analytically calculate statistical mean contrast and its variance
    if analytical_statistics:
        log.info('Calculating analytical statistics.')
        mean_stat_c = util.calc_statistical_mean_contrast(matrix, Ca, coro_floor)
        var_c = util.calc_variance_of_mean_contrast(matrix, Ca)

        with open(os.path.join(workdir, 'results', f'statistical_contrast_analytical_{c_target}.txt'), 'w') as file:
            file.write(f'Analytical, statistical mean: {mean_stat_c}')
            file.write(f'\nAnalytical variance: {var_c}')

    ### Calculate segment-based error budget
    if calculate_segment_based:
        log.info('Calculating segment-based error budget.')

        # Extract segment-based mode weights
        sigmas_opt = np.sqrt(np.diag(Cb))
        np.savetxt(os.path.join(workdir, 'results', f'mode_requirements_{c_target}_segment-based.txt'), sigmas_opt)
        ppl.plot_mode_weights_simple(sigmas_opt, wvln, out_dir=os.path.join(workdir, 'results'), c_target=c_target,
                                     fname_suffix='segment-based', save=True)
        ppl.plot_mode_weights_double_axis((sigmas, sigmas_opt), wvln, os.path.join(workdir, 'results'), c_target,
                                          fname_suffix='segment-based-vs-uniform',
                                          labels=('Uniform error budget', 'Segment-based error budget'),
                                          alphas=(0.5, 1.), linestyles=('--', '-'), colors=('k', 'r'), save=True)

        # Calculate contrast per mode
        per_mode_opt_e2e = cumulative_contrast_e2e(pmodes, sigmas_opt, luvoir, luvoir.dh_mask, individual=True)
        np.savetxt(os.path.join(workdir, 'results', f'contrast_per_mode_{c_target}_e2e_segment-based.txt'),
                   per_mode_opt_e2e)
        ppl.plot_contrast_per_mode(per_mode_opt_e2e, coro_floor, c_target, pmodes.shape[0],
                                   os.path.join(workdir, 'results'), save=True)

        # Calculate segment-based cumulative contrast
        cumulative_opt_e2e = cumulative_contrast_e2e(pmodes, sigmas_opt, luvoir, luvoir.dh_mask)
        np.savetxt(os.path.join(workdir, 'results', f'cumul_contrast_allocation_e2e_{c_target}_segment-based.txt'),
                   cumulative_opt_e2e)

        # Plot cumulative contrast from E2E simulator, segment-based vs. uniform error budget
        ppl.plot_cumulative_contrast_compare_allocation(cumulative_opt_e2e, cumulative_e2e, os.path.join(workdir, 'results'),
                                                        c_target, fname_suffix='segment-based-vs-uniform', save=True)

    ### Apply mu map and run through E2E simulator
    mus *= u.nm
    luvoir.flatten()
    for seg, mu in enumerate(mus):
        luvoir.set_segment(seg+1, mu.to(u.m).value/2, 0, 0)
    psf, ref = luvoir.calc_psf(ref=True, display_intermediate=True)
    contrast_mu = util.dh_mean(psf/ref.max(), luvoir.dh_mask)
    log.info(f'Contrast with mu-map: {contrast_mu}')

    ###
    log.info(f"All saved in {os.path.join(workdir, 'results')}")
    log.info('\nGood job')


if __name__ == '__main__':

    coro_design = CONFIG_INI.get('LUVOIR', 'coronagraph_size')
    run = CONFIG_INI.get('numerical', 'current_analysis')
    c_target = 1e-10
    mc_repeat = 100

    run_full_pastis_analysis_luvoir(coro_design, run_choice=run, c_target=c_target, n_repeat=mc_repeat)
