"""
This module contains functions that construct the matrix M for PASTIS *NUMERICALLY FROM THE RESPECTIVE E2E SIMULATOR*
 and saves it.

 Currently supported:
 JWST
 LUVOIR
 #TODO: HiCAT (already exists in notebook HiCAT/4)
 """

import os
import time
import functools
from shutil import copy
from astropy.io import fits
import astropy.units as u
import logging
import matplotlib.pyplot as plt
import numpy as np
import hcipy as hc

from config import CONFIG_INI
import util_pastis as util
from e2e_simulators.luvoir_imaging import LuvoirAPLC

log = logging.getLogger()


def num_matrix_jwst():
    """
    Generate a numerical PASTIS matrix for a JWST coronagraph.

    All inputs are read from the (local) configfile and saved to the specified output directory.
    """

    import webbpsf
    from e2e_simulators import webbpsf_imaging as webbim
    # Set WebbPSF environment variable
    os.environ['WEBBPSF_PATH'] = CONFIG_INI.get('local', 'webbpsf_data_path')

    # Keep track of time
    start_time = time.time()   # runtime is currently around 21 minutes
    log.info('Building numerical matrix for JWST\n')

    # Parameters
    overall_dir = util.create_data_path(CONFIG_INI.get('local', 'local_data_path'), telescope='jwst')
    resDir = os.path.join(overall_dir, 'matrix_numerical')
    which_tel = CONFIG_INI.get('telescope', 'name')
    nb_seg = CONFIG_INI.getint(which_tel, 'nb_subapertures')
    im_size_e2e = CONFIG_INI.getint('numerical', 'im_size_px_webbpsf')
    inner_wa = CONFIG_INI.getint(which_tel, 'IWA')
    outer_wa = CONFIG_INI.getint(which_tel, 'OWA')
    sampling = CONFIG_INI.getfloat('numerical', 'sampling')
    fpm = CONFIG_INI.get(which_tel, 'focal_plane_mask')                 # focal plane mask
    lyot_stop = CONFIG_INI.get(which_tel, 'pupil_plane_stop')   # Lyot stop
    filter = CONFIG_INI.get(which_tel, 'filter_name')
    nm_aber = CONFIG_INI.getfloat('calibration', 'calibration_aberration') * u.nm
    wss_segs = webbpsf.constants.SEGNAMES_WSS_ORDER
    zern_max = CONFIG_INI.getint('zernikes', 'max_zern')
    zern_number = CONFIG_INI.getint('calibration', 'local_zernike')
    zern_mode = util.ZernikeMode(zern_number)                       # Create Zernike mode object for easier handling
    wss_zern_nb = util.noll_to_wss(zern_number)                     # Convert from Noll to WSS framework

    # Create necessary directories if they don't exist yet
    os.makedirs(overall_dir, exist_ok=True)
    os.makedirs(resDir, exist_ok=True)
    os.makedirs(os.path.join(resDir, 'OTE_images'), exist_ok=True)
    os.makedirs(os.path.join(resDir, 'psfs'), exist_ok=True)
    os.makedirs(os.path.join(resDir, 'darkholes'), exist_ok=True)

    # Create the dark hole mask.
    pup_im = np.zeros([im_size_e2e, im_size_e2e])    # this is just used for DH mask generation
    dh_area = util.create_dark_hole(pup_im, inner_wa, outer_wa, sampling)

    # Create a direct WebbPSF image for normalization factor
    fake_aber = np.zeros([nb_seg, zern_max])
    psf_perfect = webbim.nircam_nocoro(filter, fake_aber)
    normp = np.max(psf_perfect)
    psf_perfect = psf_perfect / normp

    # Set up NIRCam coro object from WebbPSF
    nc_coro = webbpsf.NIRCam()
    nc_coro.filter = filter
    nc_coro.image_mask = fpm
    nc_coro.pupil_mask = lyot_stop

    # Null the OTE OPDs for the PSFs, maybe we will add internal WFE later.
    nc_coro, ote_coro = webbpsf.enable_adjustable_ote(nc_coro)      # create OTE for coronagraph
    nc_coro.include_si_wfe = False                                  # set SI internal WFE to zero

    #-# Generating the PASTIS matrix and a list for all contrasts
    matrix_direct = np.zeros([nb_seg, nb_seg])   # Generate empty matrix
    all_psfs = []
    all_dhs = []
    all_contrasts = []

    log.info(f'nm_aber: {nm_aber}')

    for i in range(nb_seg):
        for j in range(nb_seg):

            log.info(f'\nSTEP: {i+1}-{j+1} / {nb_seg}-{nb_seg}')

            # Get names of segments, they're being addressed by their names in the ote functions.
            seg_i = wss_segs[i].split('-')[0]
            seg_j = wss_segs[j].split('-')[0]

            # Put the aberration on the correct segments
            Aber_WSS = np.zeros([nb_seg, zern_max])         # The Zernikes here will be filled in the WSS order!!!
                                                            # Because it goes into _apply_hexikes_to_seg().
            Aber_WSS[i, wss_zern_nb - 1] = nm_aber.to(u.m).value    # Aberration on the segment we're currently working on;
                                                            # convert to meters; -1 on the Zernike because Python starts
                                                            # numbering at 0.
            Aber_WSS[j, wss_zern_nb - 1] = nm_aber.to(u.m).value    # same for other segment

            # Putting aberrations on segments i and j
            ote_coro.reset()    # Making sure there are no previous movements on the segments.
            ote_coro.zero()     # set OTE for coronagraph to zero

            # Apply both aberrations to OTE. If i=j, apply only once!
            ote_coro._apply_hexikes_to_seg(seg_i, Aber_WSS[i, :])    # set segment i  (segment numbering starts at 1)
            if i != j:
                ote_coro._apply_hexikes_to_seg(seg_j, Aber_WSS[j, :])    # set segment j

            # If you want to display it:
            # ote_coro.display_opd()
            # plt.show()

            # Save OPD images for testing
            opd_name = 'opd_' + zern_mode.name + '_' + zern_mode.convention + str(zern_mode.index) + '_segs_' + str(i+1) + '-' + str(j+1)
            plt.clf()
            ote_coro.display_opd()
            plt.savefig(os.path.join(resDir, 'OTE_images', opd_name + '.pdf'))

            log.info('Calculating WebbPSF image')
            image = nc_coro.calc_psf(fov_pixels=int(im_size_e2e), oversample=1, nlambda=1)
            psf = image[0].data / normp

            # Save WebbPSF image to disk
            filename_psf = 'psf_' + zern_mode.name + '_' + zern_mode.convention + str(zern_mode.index) + '_segs_' + str(i+1) + '-' + str(j+1)
            util.write_fits(psf, os.path.join(resDir, 'psfs', filename_psf + '.fits'), header=None, metadata=None)
            all_psfs.append(psf)

            log.info('Calculating mean contrast in dark hole')
            dh_intensity = psf * dh_area
            contrast = np.mean(dh_intensity[np.where(dh_intensity != 0)])
            log.info(f'contrast: {contrast}')

            # Save DH image to disk and put current contrast in list
            filename_dh = 'dh_' + zern_mode.name + '_' + zern_mode.convention + str(zern_mode.index) + '_segs_' + str(i+1) + '-' + str(j+1)
            util.write_fits(dh_intensity, os.path.join(resDir, 'darkholes', filename_dh + '.fits'), header=None, metadata=None)
            all_dhs.append(dh_intensity)
            all_contrasts.append(contrast)

            # Fill according entry in the matrix
            matrix_direct[i,j] = contrast

    # Transform saved lists to arrays
    all_psfs = np.array(all_psfs)
    all_dhs = np.array(all_dhs)
    all_contrasts = np.array(all_contrasts)

    # Filling the off-axis elements
    matrix_two_N = np.copy(matrix_direct)      # This is just an intermediary copy so that I don't mix things up.
    matrix_pastis = np.copy(matrix_direct)     # This will be the final PASTIS matrix.

    for i in range(nb_seg):
        for j in range(nb_seg):
            if i != j:
                matrix_off_val = (matrix_two_N[i,j] - matrix_two_N[i,i] - matrix_two_N[j,j]) / 2.
                matrix_pastis[i,j] = matrix_off_val
                log.info(f'Off-axis for i{i+1}-j{j+1}: {matrix_off_val}')

    # Normalize matrix for the input aberration
    matrix_pastis /= np.square(nm_aber.value)

    # Save matrix to file
    filename_matrix = 'PASTISmatrix_num_' + zern_mode.name + '_' + zern_mode.convention + str(zern_mode.index)
    util.write_fits(matrix_pastis, os.path.join(resDir, filename_matrix + '.fits'), header=None, metadata=None)
    log.info(f'Matrix saved to: {os.path.join(resDir, filename_matrix + ".fits")}')

    # Save the PSF and DH image *cubes* as well (as opposed to each one individually)
    util.write_fits(all_psfs, os.path.join(resDir, 'psfs', 'psf_cube' + '.fits'), header=None, metadata=None)
    util.write_fits(all_dhs, os.path.join(resDir, 'darkholes', 'dh_cube' + '.fits'), header=None, metadata=None)
    np.savetxt(os.path.join(resDir, 'pair-wise_contrasts.txt'), all_contrasts, fmt='%e')

    # Tell us how long it took to finish.
    end_time = time.time()
    log.info(f'Runtime for matrix_building.py: {end_time - start_time}sec = {(end_time - start_time) / 60}min')
    log.info(f'Data saved to {resDir}')

    # -- Runtime notes: --
    #
    # im_size = 128
    # oversampling = 1
    # nb_seg = 18
    # runtime = 20 min


def num_matrix_luvoir(design, savepsfs=False, saveopds=True):
    """
    Generate a numerical PASTIS matrix for a LUVOIR A coronagraph.

    All inputs are read from the (local) configfile and saved to the specified output directory.
    The LUVOIR STDT delivery in May 2018 included three different apodizers
    we can work with, you pick which of the three you want with the 'design' parameter.
    :param design: string, what coronagraph design to use - 'small', 'medium' or 'large'
    :param savepsfs: bool, if True, all PSFs will be saved to disk individually, as fits files, additionally to the
                     total PSF cube. If False, the total cube will still get saved at the very end of the script.
    :param saveopds: bool, if True, all pupil surface maps of aberrated segment pairs will be saved to disk as PDF
    """

    # Keep track of time
    start_time = time.time()

    ### Parameters

    # System parameters
    overall_dir = util.create_data_path(CONFIG_INI.get('local', 'local_data_path'), telescope='luvoir-'+design)
    os.makedirs(overall_dir, exist_ok=True)
    resDir = os.path.join(overall_dir, 'matrix_numerical')

    # Create necessary directories if they don't exist yet
    os.makedirs(resDir, exist_ok=True)
    os.makedirs(os.path.join(resDir, 'OTE_images'), exist_ok=True)
    os.makedirs(os.path.join(resDir, 'psfs'), exist_ok=True)

    # Set up logger
    util.setup_pastis_logging(resDir, f'pastis_matrix_{design}')
    log.info('Building numerical matrix for LUVOIR\n')

    # Read calibration aberration
    zern_number = CONFIG_INI.getint('calibration', 'local_zernike')
    zern_mode = util.ZernikeMode(zern_number)                       # Create Zernike mode object for easier handling

    # General telescope parameters
    nb_seg = CONFIG_INI.getint('LUVOIR', 'nb_subapertures')
    wvln = CONFIG_INI.getfloat('LUVOIR', 'lambda') * 1e-9  # m
    diam = CONFIG_INI.getfloat('LUVOIR', 'diameter')  # m
    wfe_aber = CONFIG_INI.getfloat('calibration', 'calibration_aberration') * 1e-9   # m

    # Image system parameters
    im_lamD = CONFIG_INI.getfloat('numerical', 'im_size_lamD_hcipy')  # image size in lambda/D
    sampling = CONFIG_INI.getfloat('numerical', 'sampling')

    # Record some of the defined parameters
    log.info(f'LUVOIR apodizer design: {design}')
    log.info(f'Wavelength: {wvln} m')
    log.info(f'Telescope diameter: {diam} m')
    log.info(f'Number of segments: {nb_seg}')
    log.info(f'Image size: {im_lamD} lambda/D')
    log.info(f'Sampling: {sampling} px per lambda/D')

    #  Copy configfile to resulting matrix directory
    util.copy_config(resDir)

    ### Instantiate Luvoir telescope with chosen apodizer design
    optics_input = CONFIG_INI.get('LUVOIR', 'optics_path')
    luvoir = LuvoirAPLC(optics_input, design, sampling)

    ### Dark hole mask
    dh_outer = hc.circular_aperture(2 * luvoir.apod_dict[design]['owa'] * luvoir.lam_over_d)(luvoir.focal_det)
    dh_inner = hc.circular_aperture(2 * luvoir.apod_dict[design]['iwa'] * luvoir.lam_over_d)(luvoir.focal_det)
    dh_mask = (dh_outer - dh_inner).astype('bool')

    ### Reference images for contrast normalization and coronagraph floor
    unaberrated_coro_psf, ref = luvoir.calc_psf(ref=True, display_intermediate=False, return_intermediate=False)
    norm = np.max(ref)

    dh_intensity = (unaberrated_coro_psf / norm) * dh_mask
    contrast_floor = np.mean(dh_intensity[np.where(dh_mask != 0)])
    log.info(f'contrast floor: {contrast_floor}')

    ### Generating the PASTIS matrix and a list for all contrasts
    matrix_direct = np.zeros([nb_seg, nb_seg])   # Generate empty matrix
    all_psfs = []
    all_contrasts = []

    log.info(f'wfe_aber: {wfe_aber} m')

    for i in range(nb_seg):
        for j in range(nb_seg):

            log.info(f'\nSTEP: {i+1}-{j+1} / {nb_seg}-{nb_seg}')

            # Put aberration on correct segments. If i=j, apply only once!
            luvoir.flatten()
            luvoir.set_segment(i+1, wfe_aber/2, 0, 0)
            if i != j:
                luvoir.set_segment(j+1, wfe_aber/2, 0, 0)

            log.info('Calculating coro image...')
            image, inter = luvoir.calc_psf(ref=False, display_intermediate=False, return_intermediate='intensity')
            # Normalize PSF by reference image
            psf = image / norm
            all_psfs.append(psf.shaped)

            # Save image to disk
            if savepsfs:   # TODO: I might want to change this to matplotlib images since I save the PSF cube anyway.
                filename_psf = 'psf_' + zern_mode.name + '_' + zern_mode.convention + str(zern_mode.index) + '_segs_' + str(i+1) + '-' + str(j+1)
                hc.write_fits(psf, os.path.join(resDir, 'psfs', filename_psf + '.fits'))

            # Save OPD images for testing (are these actually surface images, not OPD?)
            if saveopds:
                opd_name = 'opd_' + zern_mode.name + '_' + zern_mode.convention + str(zern_mode.index) + '_segs_' + str(
                    i + 1) + '-' + str(j + 1)
                plt.clf()
                hc.imshow_field(inter['seg_mirror'], mask=luvoir.aperture, cmap='RdBu')
                plt.savefig(os.path.join(resDir, 'OTE_images', opd_name + '.pdf'))

            log.info('Calculating mean contrast in dark hole')
            dh_intensity = psf * dh_mask
            contrast = np.mean(dh_intensity[np.where(dh_mask != 0)])
            log.info(f'contrast: {float(contrast)}')    # contrast is a Field, here casting to normal float
            all_contrasts.append(contrast)

            # Fill according entry in the matrix and subtract baseline contrast
            matrix_direct[i,j] = contrast - contrast_floor

    # Transform saved lists to arrays
    all_psfs = np.array(all_psfs)
    all_contrasts = np.array(all_contrasts)

    # Save the PSF image *cube* as well (as opposed to each one individually)
    hc.write_fits(all_psfs, os.path.join(resDir, 'psfs', 'psf_cube' + '.fits'),)
    np.savetxt(os.path.join(resDir, 'pair-wise_contrasts.txt'), all_contrasts, fmt='%e')

    # Filling the off-axis elements
    matrix_two_N = np.copy(matrix_direct)      # This is just an intermediary copy so that I don't mix things up.
    matrix_pastis = np.copy(matrix_direct)     # This will be the final PASTIS matrix.

    for i in range(nb_seg):
        for j in range(nb_seg):
            if i != j:
                matrix_off_val = (matrix_two_N[i,j] - matrix_two_N[i,i] - matrix_two_N[j,j]) / 2.
                matrix_pastis[i,j] = matrix_off_val
                log.info(f'Off-axis for i{i+1}-j{j+1}: {matrix_off_val}')

    # Normalize matrix for the input aberration - this defines what units the PASTIS matrix will be in. The PASTIS
    # matrix propagation function (util.pastis_contrast()) then needs to take in the aberration vector in these same
    # units. I have chosen to keep this to 1nm, so, we normalize the PASTIS matrix to units of nanometers.
    matrix_pastis /= np.square(wfe_aber * 1e9)    #  1e9 converts the calibration aberration back to nanometers

    # Save matrix to file
    filename_matrix = 'PASTISmatrix_num_' + zern_mode.name + '_' + zern_mode.convention + str(zern_mode.index)
    hc.write_fits(matrix_pastis, os.path.join(resDir, filename_matrix + '.fits'))
    log.info(f'Matrix saved to: {os.path.join(resDir, filename_matrix + ".fits")}')

    # Tell us how long it took to finish.
    end_time = time.time()
    log.info(f'Runtime for matrix_building.py: {end_time - start_time}sec = {(end_time - start_time) / 60}min')
    log.info(f'Data saved to {resDir}')
    
    return overall_dir


if __name__ == '__main__':

        # Pick the function of the telescope you want to run
        #num_matrix_jwst()

        coro_design = CONFIG_INI.get('LUVOIR', 'coronagraph_size')
        num_matrix_luvoir(design=coro_design)
