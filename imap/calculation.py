import numpy as np

def calc_irrigation(pNDVI, rain, et0, m_winter, irrigation_months, irrigation_factor, conversion_factor):
    """Calculates the irrigation required."""
    df = et0.copy()
    rain_eff = (rain * conversion_factor * 0.8) + m_winter
    
    m_start, m_end = irrigation_months
    irr_mnts = list(range(m_start, m_end + 1))
    
    is_active = df['month'].isin(range(3, 11)) | df['month'].isin(irr_mnts)
    df.loc[~is_active, 'ET0'] = 0
    df['ET0'] *= conversion_factor
    df['ETa'] = df['ET0'] * pNDVI / 0.7

    eta_off_season = df.loc[~df['month'].isin(irr_mnts), 'ETa'].sum()
    swi = (rain_eff - eta_off_season - 50 * conversion_factor) / len(irr_mnts)

    df['irrigation'] = 0.0
    mask = df['month'].isin(irr_mnts)
    df.loc[mask, 'irrigation'] = (df.loc[mask, 'ETa'] - swi).clip(lower=0)
    df['irrigation'] *= irrigation_factor

    vst = df.loc[df['month'] == 7, 'irrigation'].iloc[0] * 0.2
    df.loc[df['month'] == 7, 'irrigation'] -= vst
    df.loc[df['month'] == 8, 'irrigation'] += vst * 0.4
    df.loc[df['month'] == 9, 'irrigation'] += vst * 0.6

    df['SW1'] = (rain_eff - df['ETa'].cumsum() + df['irrigation'].cumsum()).clip(lower=0)
    df['alert'] = np.where(df['SW1'] == 0, 'drought', 'safe')

    return df
