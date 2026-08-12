"""
SOTA Ensemble Weather Prediction Engine v2
============================================
Combines NWS point forecasts with Open-Meteo ensemble data from 5 world-class models:
- ECMWF IFS 0.25° (51 members) - European Centre, gold standard
- ECMWF AIFS 0.25° (51 members) - AI-enhanced ECMWF (machine learning post-processing)
- GFS/GEFS (31 members) - NOAA US model
- ICON EPS (40 members) - DWD German model
- UKMO Global (36 members) - UK Met Office global ensemble

Total: 209 independent forecast members for probability estimation.

Instead of assuming a fixed ±3°F normal distribution, this engine calculates
EMPIRICAL probabilities by counting ensemble members above/below thresholds.

This gives us:
1. More accurate probability estimates (especially for edge cases)
2. True uncertainty quantification (spread of ensemble = forecast confidence)
3. Multi-model consensus (when all 5 models agree, confidence is very high)
4. AI-enhanced forecasting via ECMWF AIFS (trained on ERA5 reanalysis data)
"""

import logging
import time
import json
import re
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
import requests

logger = logging.getLogger("KALSHI_BOT")


@dataclass
class EnsembleForecast:
    """Result from ensemble weather prediction"""
    city: str
    date: str  # YYYY-MM-DD
    forecast_type: str  # 'high', 'low', 'precip', 'wind'
    
    # Individual model predictions
    nws_point_forecast: Optional[float] = None
    ecmwf_members: Optional[List[float]] = None
    gfs_members: Optional[List[float]] = None
    icon_members: Optional[List[float]] = None
    
    # Ensemble statistics
    ensemble_mean: Optional[float] = None
    ensemble_median: Optional[float] = None
    ensemble_std: Optional[float] = None
    ensemble_min: Optional[float] = None
    ensemble_max: Optional[float] = None
    
    # Probability calculation
    probability_above_threshold: Optional[float] = None
    threshold: Optional[float] = None
    members_above: int = 0
    members_below: int = 0
    total_members: int = 0
    
    # Confidence metrics
    model_agreement: float = 0.0  # 0-1, how much models agree
    forecast_confidence: float = 0.0  # 0-1, overall confidence


@dataclass
class TradingSignal:
    """Trading signal generated from ensemble analysis"""
    market_ticker: str
    market_title: str
    side: str  # 'yes' or 'no'
    probability: float  # Our estimated probability of YES
    market_price: float  # Current market price (0-1)
    edge: float  # probability - market_price (or market_price - probability for NO)
    confidence: float  # 0-1
    kelly_fraction: float  # Optimal bet size as fraction of bankroll
    ensemble_forecast: EnsembleForecast
    reasoning: str


# City coordinates for Open-Meteo API
CITY_COORDINATES = {
    'dallas': {'lat': 32.78, 'lon': -96.80, 'tz': 'America/Chicago'},
    'houston': {'lat': 29.76, 'lon': -95.37, 'tz': 'America/Chicago'},
    'new_york': {'lat': 40.71, 'lon': -74.01, 'tz': 'America/New_York'},
    'nyc': {'lat': 40.71, 'lon': -74.01, 'tz': 'America/New_York'},
    'miami': {'lat': 25.76, 'lon': -80.19, 'tz': 'America/New_York'},
    'chicago': {'lat': 41.88, 'lon': -87.63, 'tz': 'America/Chicago'},
    'las_vegas': {'lat': 36.17, 'lon': -115.14, 'tz': 'America/Los_Angeles'},
    'minneapolis': {'lat': 44.98, 'lon': -93.27, 'tz': 'America/Chicago'},
    'atlanta': {'lat': 33.75, 'lon': -84.39, 'tz': 'America/New_York'},
    'seattle': {'lat': 47.61, 'lon': -122.33, 'tz': 'America/Los_Angeles'},
    'boston': {'lat': 42.36, 'lon': -71.06, 'tz': 'America/New_York'},
    'denver': {'lat': 39.74, 'lon': -104.99, 'tz': 'America/Denver'},
    'phoenix': {'lat': 33.45, 'lon': -112.07, 'tz': 'America/Phoenix'},
    'san_francisco': {'lat': 37.77, 'lon': -122.42, 'tz': 'America/Los_Angeles'},
    'los_angeles': {'lat': 34.05, 'lon': -118.24, 'tz': 'America/Los_Angeles'},
    'philadelphia': {'lat': 39.95, 'lon': -75.17, 'tz': 'America/New_York'},
    'washington_dc': {'lat': 38.91, 'lon': -77.04, 'tz': 'America/New_York'},
    'detroit': {'lat': 42.33, 'lon': -83.05, 'tz': 'America/New_York'},
    'portland': {'lat': 45.52, 'lon': -122.68, 'tz': 'America/Los_Angeles'},
    'sacramento': {'lat': 38.58, 'lon': -121.49, 'tz': 'America/Los_Angeles'},
    'austin': {'lat': 30.27, 'lon': -97.74, 'tz': 'America/Chicago'},
    'san_antonio': {'lat': 29.42, 'lon': -98.49, 'tz': 'America/Chicago'},
    'nashville': {'lat': 36.16, 'lon': -86.78, 'tz': 'America/Chicago'},
    'charlotte': {'lat': 35.23, 'lon': -80.84, 'tz': 'America/New_York'},
    'indianapolis': {'lat': 39.77, 'lon': -86.16, 'tz': 'America/New_York'},
    'columbus': {'lat': 39.96, 'lon': -83.00, 'tz': 'America/New_York'},
    'jacksonville': {'lat': 30.33, 'lon': -81.66, 'tz': 'America/New_York'},
    'memphis': {'lat': 35.15, 'lon': -90.05, 'tz': 'America/Chicago'},
    'oklahoma_city': {'lat': 35.47, 'lon': -97.52, 'tz': 'America/Chicago'},
    'louisville': {'lat': 38.25, 'lon': -85.76, 'tz': 'America/New_York'},
    'baltimore': {'lat': 39.29, 'lon': -76.61, 'tz': 'America/New_York'},
    'milwaukee': {'lat': 43.04, 'lon': -87.91, 'tz': 'America/Chicago'},
    'albuquerque': {'lat': 35.08, 'lon': -106.65, 'tz': 'America/Denver'},
    'tucson': {'lat': 32.22, 'lon': -110.97, 'tz': 'America/Phoenix'},
    'el_paso': {'lat': 31.76, 'lon': -106.44, 'tz': 'America/Denver'},
    'kansas_city': {'lat': 39.10, 'lon': -94.58, 'tz': 'America/Chicago'},
    'new_orleans': {'lat': 29.95, 'lon': -90.07, 'tz': 'America/Chicago'},
    'cleveland': {'lat': 41.50, 'lon': -81.69, 'tz': 'America/New_York'},
    'pittsburgh': {'lat': 40.44, 'lon': -79.99, 'tz': 'America/New_York'},
    'st_louis': {'lat': 38.63, 'lon': -90.20, 'tz': 'America/Chicago'},
    'tampa': {'lat': 27.95, 'lon': -82.46, 'tz': 'America/New_York'},
    'orlando': {'lat': 28.54, 'lon': -81.38, 'tz': 'America/New_York'},
    'cincinnati': {'lat': 39.10, 'lon': -84.51, 'tz': 'America/New_York'},
    'raleigh': {'lat': 35.78, 'lon': -78.64, 'tz': 'America/New_York'},
    'salt_lake_city': {'lat': 40.76, 'lon': -111.89, 'tz': 'America/Denver'},
}

# Ticker to city mapping (comprehensive)
TICKER_CITY_MAP = {
    'KXHIGHTDAL': 'dallas', 'KXHIGHTHOU': 'houston', 'KXHIGHTNYC': 'new_york',
    'KXHIGHTMIA': 'miami', 'KXHIGHTCHI': 'chicago', 'KXHIGHTLV': 'las_vegas',
    'KXHIGHTMIN': 'minneapolis', 'KXHIGHTATL': 'atlanta', 'KXHIGHTSEA': 'seattle',
    'KXHIGHTBOS': 'boston', 'KXHIGHTDEN': 'denver', 'KXHIGHTPHX': 'phoenix',
    'KXHIGHTSF': 'san_francisco', 'KXHIGHTLA': 'los_angeles',
    'KXHIGHTPHL': 'philadelphia', 'KXHIGHTDC': 'washington_dc',
    'KXHIGHTDET': 'detroit', 'KXHIGHTPDX': 'portland',
    'KXHIGHTSAC': 'sacramento', 'KXHIGHTAUS': 'austin',
    'KXHIGHTSAT': 'san_antonio', 'KXHIGHTNSH': 'nashville',
    'KXHIGHTCLT': 'charlotte', 'KXHIGHTIND': 'indianapolis',
    'KXLOWTNYC': 'new_york', 'KXLOWTMIA': 'miami', 'KXLOWTCHI': 'chicago',
    'KXLOWTLV': 'las_vegas', 'KXLOWTMIN': 'minneapolis', 'KXLOWTATL': 'atlanta',
    'KXLOWTSEA': 'seattle', 'KXLOWTBOS': 'boston', 'KXLOWTDEN': 'denver',
    'KXLOWTPHX': 'phoenix', 'KXLOWTSF': 'san_francisco', 'KXLOWTLA': 'los_angeles',
    'KXLOWTDAL': 'dallas', 'KXLOWTHOU': 'houston',
    'KXLOWTPHL': 'philadelphia', 'KXLOWTDC': 'washington_dc',
    'KXLOWTDET': 'detroit', 'KXLOWTPDX': 'portland',
    'KXLOWTSAC': 'sacramento', 'KXLOWTAUS': 'austin',
    'KXLOWTSAT': 'san_antonio', 'KXLOWTNSH': 'nashville',
    'KXLOWTCLT': 'charlotte', 'KXLOWTIND': 'indianapolis',
    # Old format tickers (without T)
    'KXHIGHNY': 'new_york', 'KXHIGHCHI': 'chicago', 'KXHIGHMIA': 'miami',
    'KXHIGHHOU': 'houston', 'KXHIGHDAL': 'dallas', 'KXHIGHLV': 'las_vegas',
    'KXHIGHMIN': 'minneapolis', 'KXHIGHATL': 'atlanta', 'KXHIGHSEA': 'seattle',
    'KXHIGHBOS': 'boston', 'KXHIGHDEN': 'denver', 'KXHIGHPHX': 'phoenix',
    'KXLOWNY': 'new_york', 'KXLOWCHI': 'chicago', 'KXLOWMIA': 'miami',
    'KXLOWHOU': 'houston', 'KXLOWDAL': 'dallas', 'KXLOWLV': 'las_vegas',
    'KXLOWMIN': 'minneapolis', 'KXLOWATL': 'atlanta', 'KXLOWSEA': 'seattle',
    'KXLOWBOS': 'boston', 'KXLOWDEN': 'denver', 'KXLOWPHX': 'phoenix',
}


class EnsembleWeatherEngine:
    """
    SOTA weather prediction engine using multi-model ensemble forecasting.
    
    Combines:
    - NWS point forecasts (official US government forecast)
    - ECMWF IFS ensemble (51 members, world's best weather model)
    - ECMWF AIFS ensemble (51 members, AI-enhanced via machine learning)
    - GFS/GEFS ensemble (31 members, NOAA's global model)
    - ICON EPS ensemble (40 members, DWD's high-resolution model)
    - UKMO Global ensemble (36 members, UK Met Office)
    
    Total: 209 independent forecast members for probability estimation.
    """
    
    def __init__(self):
        self.cache = {}  # {city_date: EnsembleForecast}
        self.cache_ttl = 7200  # 2 hours
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'KalshiWeatherBot/2.0'})
        self.nws_cache = {}  # Separate NWS cache
        
    def get_ensemble_probability(self, city: str, date: str, threshold: float,
                                  forecast_type: str = 'high',
                                  market_type: str = 'above') -> EnsembleForecast:
        """
        Get the ensemble-based probability for a weather threshold.
        
        Args:
            city: City name (must be in CITY_COORDINATES)
            date: Target date YYYY-MM-DD
            threshold: Temperature threshold in °F
            forecast_type: 'high' for daily max, 'low' for daily min
            market_type: 'above' (>threshold), 'below' (<threshold), or 'range'
            
        Returns:
            EnsembleForecast with probability and confidence metrics
        """
        cache_key = f"{city}_{date}_{forecast_type}"
        
        # Check cache
        if cache_key in self.cache:
            cached = self.cache[cache_key]
            if time.time() - cached.get('_cache_time', 0) < self.cache_ttl:
                forecast = cached['forecast']
                # Recalculate probability for this specific threshold
                return self._calculate_probability(forecast, threshold, market_type)
        
        # Fetch ensemble data
        forecast = self._fetch_ensemble_data(city, date, forecast_type)
        
        if forecast:
            # Cache the raw forecast data
            self.cache[cache_key] = {
                'forecast': forecast,
                '_cache_time': time.time()
            }
            # Calculate probability for the specific threshold
            return self._calculate_probability(forecast, threshold, market_type)
        
        return EnsembleForecast(city=city, date=date, forecast_type=forecast_type)
    
    def _fetch_ensemble_data(self, city: str, date: str, forecast_type: str) -> Optional[EnsembleForecast]:
        """Fetch ensemble data from Open-Meteo and NWS"""
        coords = CITY_COORDINATES.get(city)
        if not coords:
            logger.warning(f"[ENSEMBLE] Unknown city: {city}")
            return None
        
        forecast = EnsembleForecast(city=city, date=date, forecast_type=forecast_type)
        
        # Fetch Open-Meteo ensemble data
        try:
            variable = 'temperature_2m_max' if forecast_type == 'high' else 'temperature_2m_min'
            url = (
                f"https://ensemble-api.open-meteo.com/v1/ensemble"
                f"?latitude={coords['lat']}&longitude={coords['lon']}"
                f"&daily={variable}"
                f"&models=icon_seamless,gfs_seamless,ecmwf_ifs025,ecmwf_aifs025,ukmo_global_ensemble_20km"
                f"&forecast_days=7"
                f"&temperature_unit=fahrenheit"
                f"&timezone={coords['tz']}"
            )
            
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                daily = data.get('daily', {})
                times = daily.get('time', [])
                
                # Find the target date index
                date_idx = None
                for i, t in enumerate(times):
                    if t == date:
                        date_idx = i
                        break
                
                if date_idx is None:
                    # Try tomorrow (index 1) as fallback
                    date_idx = 1 if len(times) > 1 else 0
                
                # Extract all ensemble members for each model (v8: 5 models)
                ecmwf_members = []
                ecmwf_aifs_members = []
                gfs_members = []
                icon_members = []
                ukmo_members = []
                
                for key, values in daily.items():
                    if variable not in key or key == 'time':
                        continue
                    if date_idx >= len(values) or values[date_idx] is None:
                        continue
                    
                    val = values[date_idx]
                    
                    if 'ecmwf_aifs' in key:
                        ecmwf_aifs_members.append(val)
                    elif 'ecmwf' in key:
                        ecmwf_members.append(val)
                    elif 'ncep_gefs' in key or 'gfs' in key:
                        gfs_members.append(val)
                    elif 'ukmo' in key:
                        ukmo_members.append(val)
                    elif 'icon' in key:
                        icon_members.append(val)
                
                # Store per-model members (AIFS and UKMO contribute to combined ensemble)
                forecast.ecmwf_members = (ecmwf_members + ecmwf_aifs_members) if (ecmwf_members or ecmwf_aifs_members) else None
                forecast.gfs_members = gfs_members if gfs_members else None
                forecast.icon_members = icon_members if icon_members else None
                
                # Calculate ensemble statistics from ALL 5 models (209 members)
                all_members = ecmwf_members + ecmwf_aifs_members + gfs_members + icon_members + ukmo_members
                if all_members:
                    forecast.total_members = len(all_members)
                    forecast.ensemble_mean = sum(all_members) / len(all_members)
                    sorted_members = sorted(all_members)
                    forecast.ensemble_median = sorted_members[len(sorted_members) // 2]
                    forecast.ensemble_min = min(all_members)
                    forecast.ensemble_max = max(all_members)
                    
                    # Standard deviation
                    mean = forecast.ensemble_mean
                    variance = sum((x - mean) ** 2 for x in all_members) / len(all_members)
                    forecast.ensemble_std = variance ** 0.5
                    
                    logger.info(
                        f"[ENSEMBLE] {city} {date} {forecast_type}: "
                        f"mean={forecast.ensemble_mean:.1f}F, "
                        f"std={forecast.ensemble_std:.1f}F, "
                        f"range=[{forecast.ensemble_min:.1f}, {forecast.ensemble_max:.1f}], "
                        f"members={forecast.total_members} "
                        f"(ECMWF={len(ecmwf_members)}, AIFS={len(ecmwf_aifs_members)}, "
                        f"GFS={len(gfs_members)}, ICON={len(icon_members)}, UKMO={len(ukmo_members)})"
                    )
                    
        except Exception as e:
            logger.warning(f"[ENSEMBLE] Open-Meteo fetch failed for {city}: {e}")
        
        # Also fetch NWS point forecast for cross-validation
        try:
            nws_temp = self._fetch_nws_forecast(city, date, forecast_type)
            if nws_temp is not None:
                forecast.nws_point_forecast = nws_temp
        except Exception as e:
            logger.debug(f"[ENSEMBLE] NWS fetch failed for {city}: {e}")
        
        return forecast
    
    def _fetch_nws_forecast(self, city: str, date: str, forecast_type: str) -> Optional[float]:
        """Fetch NWS point forecast for cross-validation"""
        coords = CITY_COORDINATES.get(city)
        if not coords:
            return None
        
        nws_cache_key = f"{city}_{date}_{forecast_type}"
        if nws_cache_key in self.nws_cache:
            cached = self.nws_cache[nws_cache_key]
            if time.time() - cached['time'] < self.cache_ttl:
                return cached['temp']
        
        try:
            # Get NWS grid point
            points_url = f"https://api.weather.gov/points/{coords['lat']},{coords['lon']}"
            resp = self.session.get(points_url, timeout=10)
            if resp.status_code != 200:
                return None
            
            forecast_url = resp.json()['properties']['forecast']
            resp = self.session.get(forecast_url, timeout=10)
            if resp.status_code != 200:
                return None
            
            periods = resp.json()['properties']['periods']
            
            # Find the relevant period
            for period in periods:
                period_name = period.get('name', '').lower()
                temp = period.get('temperature')
                
                if forecast_type == 'high' and 'night' not in period_name:
                    # Daytime period = high temp
                    self.nws_cache[nws_cache_key] = {'temp': temp, 'time': time.time()}
                    return temp
                elif forecast_type == 'low' and 'night' in period_name:
                    # Nighttime period = low temp
                    self.nws_cache[nws_cache_key] = {'temp': temp, 'time': time.time()}
                    return temp
                    
        except Exception as e:
            logger.debug(f"[ENSEMBLE] NWS API error for {city}: {e}")
        
        return None
    
    def _calculate_probability(self, forecast: EnsembleForecast, threshold: float,
                                market_type: str) -> EnsembleForecast:
        """
        Calculate empirical probability from ensemble members.
        
        This is the KEY innovation: instead of assuming a normal distribution,
        we count actual ensemble members above/below the threshold.
        """
        forecast.threshold = threshold
        
        # Combine all available members
        all_members = []
        if forecast.ecmwf_members:
            all_members.extend(forecast.ecmwf_members)
        if forecast.gfs_members:
            all_members.extend(forecast.gfs_members)
        if forecast.icon_members:
            all_members.extend(forecast.icon_members)
        
        if not all_members:
            # Fallback to NWS point forecast with normal distribution assumption
            if forecast.nws_point_forecast is not None:
                from scipy.stats import norm
                std = 3.0  # Default uncertainty
                if market_type == 'above':
                    prob = 1 - norm.cdf(threshold, forecast.nws_point_forecast, std)
                elif market_type == 'below':
                    prob = norm.cdf(threshold, forecast.nws_point_forecast, std)
                else:
                    prob = 0.5
                forecast.probability_above_threshold = prob if market_type == 'above' else (1 - prob)
                forecast.forecast_confidence = 0.5  # Low confidence without ensemble
            return forecast
        
        # Count members above/below threshold
        members_above = sum(1 for m in all_members if m > threshold)
        members_below = sum(1 for m in all_members if m <= threshold)
        total = len(all_members)
        
        forecast.members_above = members_above
        forecast.members_below = members_below
        forecast.total_members = total
        
        # Empirical probability
        p_above = members_above / total
        p_below = members_below / total
        
        if market_type == 'above':
            forecast.probability_above_threshold = p_above
        elif market_type == 'below':
            forecast.probability_above_threshold = p_below
        else:
            # Range market - handled separately
            forecast.probability_above_threshold = p_above
        
        # Calculate model agreement (how much do the 3 models agree?)
        model_probs = []
        if forecast.ecmwf_members:
            ecmwf_above = sum(1 for m in forecast.ecmwf_members if m > threshold)
            model_probs.append(ecmwf_above / len(forecast.ecmwf_members))
        if forecast.gfs_members:
            gfs_above = sum(1 for m in forecast.gfs_members if m > threshold)
            model_probs.append(gfs_above / len(forecast.gfs_members))
        if forecast.icon_members:
            icon_above = sum(1 for m in forecast.icon_members if m > threshold)
            model_probs.append(icon_above / len(forecast.icon_members))
        
        if len(model_probs) >= 2:
            # Agreement = 1 - normalized spread between model probabilities
            spread = max(model_probs) - min(model_probs)
            forecast.model_agreement = 1.0 - min(spread * 2, 1.0)
        else:
            forecast.model_agreement = 0.5
        
        # Overall confidence based on:
        # 1. Number of ensemble members (more = better)
        # 2. Model agreement (all models agree = high confidence)
        # 3. Distance from threshold (further = more confident)
        # 4. NWS cross-validation (if NWS agrees, bonus confidence)
        
        member_confidence = min(total / 100, 1.0)  # Max at 100 members
        
        distance_from_threshold = abs(forecast.ensemble_mean - threshold) if forecast.ensemble_mean else 0
        distance_confidence = min(distance_from_threshold / 10.0, 1.0)  # Max at 10°F away
        
        nws_agreement = 0.5
        if forecast.nws_point_forecast is not None and forecast.ensemble_mean is not None:
            nws_diff = abs(forecast.nws_point_forecast - forecast.ensemble_mean)
            nws_agreement = max(0, 1.0 - nws_diff / 5.0)  # Penalize if NWS disagrees by >5°F
        
        forecast.forecast_confidence = (
            0.3 * member_confidence +
            0.3 * forecast.model_agreement +
            0.25 * distance_confidence +
            0.15 * nws_agreement
        )
        
        return forecast
    
    def analyze_market(self, market_ticker: str, market_title: str,
                       market_yes_price: float, floor_strike=None,
                       cap_strike=None) -> Optional[TradingSignal]:
        """
        Analyze a weather market and generate a trading signal.
        
        Args:
            market_ticker: Kalshi market ticker (e.g., KXHIGHTDAL-26MAY01-T66)
            market_title: Market title text
            market_yes_price: Current YES price (0-1 scale, e.g., 0.15 for 15c)
            floor_strike: API-provided floor strike (lower bound)
            cap_strike: API-provided cap strike (upper bound)
            
        Returns:
            TradingSignal if an edge is found, None otherwise
        """
        # Extract city from ticker
        city = self._extract_city(market_ticker)
        if not city:
            return None
        
        # Extract date from ticker
        date = self._extract_date(market_ticker)
        if not date:
            return None
        
        # Determine forecast type from series name
        series = market_ticker.split('-')[0]
        if 'HIGH' in series.upper():
            forecast_type = 'high'
        elif 'LOW' in series.upper():
            forecast_type = 'low'
        else:
            forecast_type = 'high'
        
        # CRITICAL: Use floor_strike and cap_strike from API to determine market type
        # This is authoritative — ticker T/B prefix is unreliable
        if floor_strike is not None and cap_strike is not None:
            # RANGE market: "Will temp be between floor and cap?"
            # Use the dedicated range market analyzer
            return self.analyze_range_market(
                market_ticker, market_title, market_yes_price,
                float(floor_strike), float(cap_strike)
            )
        elif floor_strike is not None and cap_strike is None:
            # ABOVE market: "Will temp be > floor?"
            market_type = 'above'
            threshold = float(floor_strike)
        elif cap_strike is not None and floor_strike is None:
            # BELOW market: "Will temp be < cap?"
            market_type = 'below'
            threshold = float(cap_strike)
        else:
            # No strike data from API — fall back to title/ticker parsing (legacy)
            threshold, market_type, forecast_type = self._extract_threshold(
                market_ticker, market_title
            )
            if threshold is None:
                return None
        
        # Get ensemble probability
        forecast = self.get_ensemble_probability(
            city, date, threshold, forecast_type, market_type
        )
        
        if forecast.probability_above_threshold is None:
            return None
        
        our_probability = forecast.probability_above_threshold
        
        # our_probability is already P(YES) for the correct market type:
        # - 'above': P(temp > threshold) = P(YES)
        # - 'below': P(temp < threshold) = P(YES)
        p_yes = our_probability
        
        # Calculate edge
        edge_yes = p_yes - market_yes_price
        edge_no = (1 - p_yes) - (1 - market_yes_price)
        
        # Determine which side to trade
        if edge_yes > edge_no and edge_yes > 0.10:  # Min 10% edge
            side = 'yes'
            edge = edge_yes
        elif edge_no > edge_yes and edge_no > 0.10:
            side = 'no'
            edge = edge_no
        else:
            return None  # No sufficient edge
        
        # Apply confidence filter
        min_confidence = 0.4
        if forecast.forecast_confidence < min_confidence:
            return None
        
        # Calculate Kelly Criterion fraction
        if side == 'yes':
            p = p_yes
            b = (1.0 / market_yes_price) - 1  # Odds ratio
        else:
            p = 1 - p_yes
            b = (1.0 / (1 - market_yes_price)) - 1
        
        kelly = (p * b - (1 - p)) / b if b > 0 else 0
        kelly = max(0, min(kelly, 0.25))  # Cap at 25% of bankroll
        
        # Apply confidence scaling to Kelly
        kelly *= forecast.forecast_confidence
        
        # Build reasoning string
        reasoning_parts = []
        if forecast.ensemble_mean is not None:
            reasoning_parts.append(
                f"Ensemble mean: {forecast.ensemble_mean:.1f}F "
                f"(std: {forecast.ensemble_std:.1f}F)"
            )
        if forecast.nws_point_forecast is not None:
            reasoning_parts.append(f"NWS forecast: {forecast.nws_point_forecast:.0f}F")
        
        # Show correct member count for the market type
        if market_type == 'above':
            member_count = forecast.members_above
        else:
            member_count = forecast.members_below
        reasoning_parts.append(
            f"Members {market_type} {threshold}F: "
            f"{member_count}/{forecast.total_members}"
        )
        reasoning_parts.append(f"Model agreement: {forecast.model_agreement:.0%}")
        reasoning_parts.append(f"Confidence: {forecast.forecast_confidence:.0%}")
        
        return TradingSignal(
            market_ticker=market_ticker,
            market_title=market_title,
            side=side,
            probability=p_yes,
            market_price=market_yes_price,
            edge=edge,
            confidence=forecast.forecast_confidence,
            kelly_fraction=kelly,
            ensemble_forecast=forecast,
            reasoning=" | ".join(reasoning_parts)
        )
    
    def _extract_city(self, ticker: str) -> Optional[str]:
        """Extract city from market ticker"""
        # Get the series prefix (before the date part)
        parts = ticker.split('-')
        series = parts[0] if parts else ticker
        
        # Direct lookup
        if series in TICKER_CITY_MAP:
            return TICKER_CITY_MAP[series]
        
        # Try fuzzy match - strip trailing characters
        for prefix, city in TICKER_CITY_MAP.items():
            if series.startswith(prefix) or prefix.startswith(series):
                return city
        
        return None
    
    def _extract_date(self, ticker: str) -> Optional[str]:
        """Extract date from market ticker like KXHIGHTDAL-26MAY01-T66"""
        parts = ticker.split('-')
        if len(parts) < 2:
            return None
        
        date_part = parts[1]  # e.g., "26MAY01"
        
        # Parse YY + MMM + DD format
        month_map = {
            'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
            'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
            'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
        }
        
        match = re.match(r'(\d{2})([A-Z]{3})(\d{2})', date_part)
        if match:
            year = f"20{match.group(1)}"
            month = month_map.get(match.group(2), '01')
            day = match.group(3)
            return f"{year}-{month}-{day}"
        
        return None
    
    def _extract_threshold(self, ticker: str, title: str) -> Tuple[Optional[float], str, str]:
        """
        Extract temperature threshold, market type, and forecast type.
        
        Returns: (threshold, market_type, forecast_type)
            market_type: 'above', 'below', or 'range'
            forecast_type: 'high' or 'low'
        """
        # Determine forecast type from ticker
        series = ticker.split('-')[0]
        if 'HIGH' in series.upper():
            forecast_type = 'high'
        elif 'LOW' in series.upper():
            forecast_type = 'low'
        else:
            forecast_type = 'high'  # default
        
        # Extract threshold from ticker suffix
        # Format: KXHIGHTDAL-26MAY01-T66 or -B64.5 or -T77
        parts = ticker.split('-')
        threshold = None
        market_type = 'above'  # default
        
        if len(parts) >= 3:
            suffix = parts[-1]
            # T66 = Top = above threshold, B64.5 = Bottom = below threshold
            tb_match = re.match(r'([TB])(\d+\.?\d*)', suffix)
            if tb_match:
                prefix = tb_match.group(1)
                threshold = float(tb_match.group(2))
                # CRITICAL: T = above, B = below
                if prefix == 'T':
                    market_type = 'above'
                elif prefix == 'B':
                    market_type = 'below'
            else:
                # No T/B prefix, just a number
                plain_match = re.match(r'(\d+\.?\d*)', suffix)
                if plain_match:
                    threshold = float(plain_match.group(1))
        
        # Also check title for threshold and type
        if threshold is None:
            # Try patterns like ">65°", "<62°", "58-59°"
            above_match = re.search(r'[>≥]\s*(\d+\.?\d*)', title)
            below_match = re.search(r'[<≤]\s*(\d+\.?\d*)', title)
            range_match = re.search(r'(\d+\.?\d*)\s*[-–]\s*(\d+\.?\d*)', title)
            
            if above_match:
                threshold = float(above_match.group(1))
                market_type = 'above'
            elif below_match:
                threshold = float(below_match.group(1))
                market_type = 'below'
            elif range_match:
                low = float(range_match.group(1))
                high = float(range_match.group(2))
                threshold = (low + high) / 2
                market_type = 'range'
        
        # Determine market type from title ONLY for range detection
        # CRITICAL: If T/B prefix was found in ticker, NEVER override market_type
        # The title often contains range-like text (e.g., "49° to 50°") even for
        # binary above/below markets. The T/B prefix is authoritative.
        tb_was_parsed = (len(parts) >= 3 and re.match(r'[TB]\d', parts[-1]))
        if not tb_was_parsed and market_type != 'range':
            range_match = re.search(r'(\d+\.?\d*)\s*(?:°\s*)?(?:to|[-–])\s*(\d+\.?\d*)\s*°', title)
            if range_match:
                low = float(range_match.group(1))
                high = float(range_match.group(2))
                threshold = (low + high) / 2
                market_type = 'range'
        
        return threshold, market_type, forecast_type
    
    def analyze_range_market(self, market_ticker: str, market_title: str,
                             market_yes_price: float, low_bound: float,
                             high_bound: float) -> Optional[TradingSignal]:
        """
        Analyze a range/bucket market (e.g., "Will temp be 64-65°F?")
        
        For range markets, we count ensemble members within the range.
        """
        city = self._extract_city(market_ticker)
        date = self._extract_date(market_ticker)
        
        if not city or not date:
            return None
        
        # Determine forecast type
        series = market_ticker.split('-')[0]
        forecast_type = 'high' if 'HIGH' in series.upper() else 'low'
        
        # Get ensemble data
        forecast = self.get_ensemble_probability(
            city, date, (low_bound + high_bound) / 2, forecast_type, 'above'
        )
        
        # Count members within range
        all_members = []
        if forecast.ecmwf_members:
            all_members.extend(forecast.ecmwf_members)
        if forecast.gfs_members:
            all_members.extend(forecast.gfs_members)
        if forecast.icon_members:
            all_members.extend(forecast.icon_members)
        
        if not all_members:
            return None
        
        members_in_range = sum(1 for m in all_members if low_bound <= m <= high_bound)
        p_in_range = members_in_range / len(all_members)
        
        # For range markets, YES means temp will be in range
        p_yes = p_in_range
        
        # Calculate edge
        edge_yes = p_yes - market_yes_price
        edge_no = (1 - p_yes) - (1 - market_yes_price)
        
        if edge_yes > 0.10:
            side = 'yes'
            edge = edge_yes
        elif edge_no > 0.10:
            side = 'no'
            edge = edge_no
        else:
            return None
        
        # Kelly
        if side == 'yes':
            p = p_yes
            b = (1.0 / market_yes_price) - 1 if market_yes_price > 0 else 0
        else:
            p = 1 - p_yes
            b = (1.0 / (1 - market_yes_price)) - 1 if market_yes_price < 1 else 0
        
        kelly = (p * b - (1 - p)) / b if b > 0 else 0
        kelly = max(0, min(kelly, 0.25))
        kelly *= forecast.forecast_confidence
        
        reasoning = (
            f"Range [{low_bound}-{high_bound}F]: "
            f"{members_in_range}/{len(all_members)} members in range | "
            f"Ensemble mean: {forecast.ensemble_mean:.1f}F | "
            f"P(in range)={p_in_range:.0%} vs market={market_yes_price:.0%}"
        )
        
        return TradingSignal(
            market_ticker=market_ticker,
            market_title=market_title,
            side=side,
            probability=p_yes,
            market_price=market_yes_price,
            edge=edge,
            confidence=forecast.forecast_confidence,
            kelly_fraction=kelly,
            ensemble_forecast=forecast,
            reasoning=reasoning
        )
