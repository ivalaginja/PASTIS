"""
This script applies the analytical model in the case of one single Zernike polynomial
on the segments.
We're following the Noll convention starting with index 0
0> piston, 1: tip, 2: tilt, 3: defocus, 4: 45°-astigmatism, and so on...
"""

import os
import numpy as np
from astropy.io import fits
import poppy.zernike as zern
import matplotlib.pyplot as plt

from python.config import CONFIG_INI
import python.util_pastis as util


if __name__ == "__main__":

    #-# Define parameters
    dataDir = os.path.join('..', 'data', 'py_data')
    nb_seg = CONFIG_INI.getint('telescope', 'nb_subapertures')
    wvln = CONFIG_INI.getint('filter', 'lambda')
    inner_wa = CONFIG_INI.getint('coronagraph', 'IWA')
    outer_wa = CONFIG_INI.getint('coronagraph', 'OWA')
    tel_size_px = CONFIG_INI.getint('numerical', 'tel_size_px')        # pupil diameter of telescope in pixels
    im_size = CONFIG_INI.getint('numerical', 'im_size_px')             # image array size in px
    px_nm = CONFIG_INI.getfloat('numerical', 'px_size_nm')                      # pixel size in nm
    sampling = CONFIG_INI.getfloat('numerical', 'sampling')            # "fake" sampling; multiply by tel_size_px/im_size to scale it and get the real sampling
    real_samp = sampling * tel_size_px / im_size                       # real sampling - effectively lambda/D
    largeur = tel_size_px * sampling                                   # ; size of pupil (?) with taking the sampling into account - as opposed to the 708 of total image
    wave_number = 2. * np.pi / wvln
    focal = 2. * px_nm * CONFIG_INI.getfloat('telescope', 'diameter')*1e9 / wvln    # focal length of the telescope
    size_tel = CONFIG_INI.getfloat('telescope', 'diameter')*1e9 / tel_size_px   # size of one pixel in pupil in nm
    px_square_2rad = size_tel * px_nm * wave_number / focal
    zern_max = CONFIG_INI.getint('zernikes', 'max_zern')

    zernike_pol = 0
    A = np.zeros(nb_seg + 1)
    A[9] = 1.
    coef = A
    cali = False   # Determine whether you want the calibration to take place or not

    # Create the pupil image
    pup_im = np.zeros((im_size, im_size))

    #-# Generate a dark hole
    circ_inner = util.circle_mask(pup_im, pup_im.shape[0]/2., pup_im.shape[1]/2., inner_wa * real_samp) * 1
    circ_outer = util.circle_mask(pup_im, pup_im.shape[0]/2., pup_im.shape[1]/2., outer_wa * real_samp) * 1
    dh_area = circ_outer - circ_inner

    #-# Mean subtraction for piston
    coef = coef / 2. * np.pi / wvln

    if zernike_pol == 0:
        coef -= np.mean(coef)

    #-# Generic segment shape
    pupil = fits.getdata(os.path.join(dataDir, 'pupil.fits'))
    mini_seg = np.zeros((100,100))   # jsut a stand-in for now

    #-# Import baseline information

    Baseline_vec = fits.getdata(os.path.join(dataDir, 'Baseline_vec.fits'))
    Projection_Matrix = fits.getdata(os.path.join(dataDir, 'Projection_Matrix.fits'))
    vec_list = fits.getdata(os.path.join(dataDir, 'vec_list.fits'))
    NR_pairs_list_int = fits.getdata(os.path.join(dataDir, 'NR_pairs_list_int.fits'))

    # Figure out how many NRPs we're dealing with
    NR_pairs_nb = NR_pairs_list_int.shape[0]

    #-# Calibration about to happen yes or no
    if cali:
        if zernike_pol == 1:
            ck = np.sqrt(fits.getdata(os.path.join(dataDir, 'Calibration_Tip.fits')))
        elif zernike_pol == 2:
            ck = np.sqrt(fits.getdata(os.path.join(dataDir, 'Calibration_Tilt.fits')))
        elif zernike_pol == 3:
            ck = np.sqrt(fits.getdata(os.path.join(dataDir, 'Calibration_Focus.fits')))
        elif zernike_pol == 4:
            ck = np.sqrt(fits.getdata(os.path.join(dataDir, 'Calibration_Astig45.fits')))
        elif zernike_pol == 5:
            ck = np.sqrt(fits.getdata(os.path.join(dataDir, 'Calibration_Astig0.fits')))
    else:
        ck = np.ones(nb_seg + 1)

    coef = coef * ck

    #-# Generic coefficients
    generic_coef = np.zeros(NR_pairs_nb)

    for q in range(NR_pairs_nb):
        for i in range(nb_seg + 1):
            for j in range(i+1, nb_seg):
                if Projection_Matrix[i, j, 0] == q+1:
                    generic_coef[q] = generic_coef[q] + coef[i] * coef[j]

    #-# Constant sum and cosine sum
    # I gotta figure out in what way to actually to do int() or mod()/%, because largeur is a float here
    tab_i = np.reshape(np.arange(int(largeur ** 2)), (int(largeur), int(largeur))) - largeur/2. + 0.5
    tab_j = np.transpose(tab_i)
    cos_u_mat = np.zeros((int(largeur), int(largeur), NR_pairs_nb))

    # Please explain what on Earth is happening here
    for q in range(NR_pairs_nb):
        cos_u_mat[:,:,q] = np.cos(px_square_2rad * (vec_list[NR_pairs_list_int[q,0], NR_pairs_list_int[q, 1], 0] * tab_i) + px_square_2rad * (vec_list[NR_pairs_list_int[q, 0], NR_pairs_list_int[q, 1], 1] * tab_j))

    sum1 = np.sum(coef**2)
    sum2 = np.zeros((int(largeur), int(largeur)))

    for q in range (NR_pairs_nb):
        sum2 = sum2 + generic_coef[q] * cos_u_mat[:,:,q]

    #-# Local Zernike
    # Calculate the Zernike that is currently being used and put it on one single subaperture, the result is Zer
    size_seg = 100
    isolated_zerns = zern.hexike_basis(nterms=zern_max, npix=size_seg, rho=None, theta=None, vertical=False, outside=0.0)

    if zernike_pol == 0:
        Zer = mini_seg
    elif zernike_pol == 1:
        Zer = mini_seg * isolated_zerns[1]
    elif zernike_pol == 2:
        Zer = mini_seg * isolated_zerns[2]
    elif zernike_pol == 3:
        Zer = mini_seg * isolated_zerns[3]
    elif zernike_pol == 4:
        Zer = mini_seg * isolated_zerns[4]
    elif zernike_pol == 5:
        Zer = mini_seg * isolated_zerns[5]

    #-# Final image
    # Generating the final image that will get passed on to the outer scope
    # I need to blow up the result from the FT to the size of sum2
    TF_seg = np.abs(util.FFT(Zer)**2 * (sum1 + 2. * sum2))
    TF_seg_zoom = util.zoom(TF_seg, TF_seg.shape[0]/2, TF_seg.shape[1]/2, 20)
    dh_area_zoom = util.zoom(dh_area, dh_area.shape[0]/2, dh_area.shape[1]/2, 20)

    DH_PSF = dh_area_zoom * TF_seg_zoom
