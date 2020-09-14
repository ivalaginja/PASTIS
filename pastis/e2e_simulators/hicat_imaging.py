"""
This module contains useful functions to interface with the HiCAT simulator.
"""

import logging
import hicat.simulators
from pastis.config import CONFIG_INI
import pastis.util_pastis as util

log = logging.getLogger()


def set_up_hicat(apply_continuous_dm_maps=False):
    """
    Return a configured instance of the HiCAT simulator.

    Sets the pupil mask, whether the IrisAO is in or out, apodizer, Lyot stop and detector. Optionally, loads DM maps
    onto the two continuous face-sheet Boston DMs.
    :param apply_continuous_dm_maps: bool, whether to load BostonDM maps from path specified in configfile, default False
    :return: instance of HICAT_Sim()
    """

    hicat_sim = hicat.simulators.hicat_sim.HICAT_Sim()

    hicat_sim.pupil_maskmask = 'circular'  # I will likely have to implement a new pupil mask
    hicat_sim.iris_ao = 'iris_ao'
    hicat_sim.apodizer = 'no_apodizer'
    hicat_sim.lyot_stop = 'circular'
    hicat_sim.detector = 'imager'

    log.info(hicat_sim.describe())

    # Load Boston DM maps into HiCAT simulator
    if apply_continuous_dm_maps:
        path_to_dh_solution = CONFIG_INI.get('HiCAT', 'dm_maps_path')
        dm1_surface, dm2_surface = util.read_continuous_dm_maps_hicat(path_to_dh_solution)
        hicat_sim.dm1.set_surface(dm1_surface)
        hicat_sim.dm2.set_surface(dm2_surface)

        log.info(f'BostonDM maps applied from {path_to_dh_solution}.')

    return hicat_sim
