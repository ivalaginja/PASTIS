"""
Run different cases, free combination of matrices and analysis scripts.
"""
import os
from hockeystick_contrast_curve import hockeystick_luvoir
from matrix_building_numerical import num_matrix_luvoir
from modal_analysis import run_full_pastis_analysis_luvoir
from optimized_error_budget import build_mode_based_error_budget
from config import CONFIG_INI

if __name__ == '__main__':
    
    # First generate a couple of matrices
    dir_small = num_matrix_luvoir(design='small')
    #dir_medium = num_matrix_luvoir(design='medium')
    #dir_large = num_matrix_luvoir(design='large')
    
    # Then generate all hockeystick curves
    #dir_small = os.path.join(CONFIG_INI.get('local', 'local_data_path'), 'your-data-directory_small')
    result_dir_small = os.path.join(dir_small, 'results')
    matrix_dir_small = os.path.join(dir_small, 'matrix_numerical')
    hockeystick_luvoir(apodizer_choice='small', matrixdir=matrix_dir_small, resultdir=result_dir_small, range_points=50, no_realizations=20)

    #dir_medium = os.path.join(CONFIG_INI.get('local', 'local_data_path'), 'your-data-directory_medium')
    #result_dir_medium = os.path.join(dir_medium, 'results')
    #matrix_dir_medium = os.path.join(dir_medium, 'matrix_numerical')
    #hockeystick_luvoir(apodizer_choice='medium', matrixdir=matrix_dir_medium, resultdir=result_dir_medium, range_points=50, no_realizations=20)

    #dir_large = os.path.join(CONFIG_INI.get('local', 'local_data_path'), 'your-data-directory_medium')
    #result_dir_large = os.path.join(dir_large, 'results')
    #matrix_dir_large = os.path.join(dir_large, 'matrix_numerical')
    #hockeystick_luvoir(apodizer_choice='large', matrixdir=matrix_dir_large, resultdir=result_dir_large, range_points=50, no_realizations=20)
    
    # Finally run full analysis on all three cases
    run_full_pastis_analysis_luvoir(design='small', run_choice=dir_small)
    #run_full_pastis_analysis_luvoir(design='medium', run_choice=dir_medium)
    #run_full_pastis_analysis_luvoir(design='large', run_choice=dir_large)

    # Calculate independent-segment error budget
    build_mode_based_error_budget(design='small', run_choice=dir_small, error_budget='optimized')
    #build_mode_based_error_budget(design='medium', run_choice=dir_medium, error_budget='optimized')
    #build_mode_based_error_budget(design='large', run_choice=dir_large, error_budget='optimized')