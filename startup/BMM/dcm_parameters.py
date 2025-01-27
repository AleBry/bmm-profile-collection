
class dcm_parameters():
    '''A simple class for maintaining calibration parameters for the
    Si(111) and Si(311) monochromators.

    Parameters
    ----------
    BMM_dcm.dspacing_111 : float
        d-spacing for the Si(111) mono
    BMM_offset_111 : float
        angular offset for the Si(111) mono
    BMM_dcm.dspacing_311 : float
        d-spacing for the Si(311) mono
    BMM_offset_311 : float
        angular offset for the Si(311) mono

    '''

    def __init__(self):
        self.dspacing_111 = 3.1354610  # 12 September, 2024
        self.dspacing_311 = 1.6376096  # 12 September, 2024

        self.offset_111 = 16.0934446   # 12 September, 2024
        self.offset_311 = 16.0018360   # 12 September, 2024
        
