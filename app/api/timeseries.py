from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from scipy.signal import savgol_filter
import ee
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

router = APIRouter()
@router.get("/landsat/{lat}/{lon}")
def timeseries_landsat(
    lat: float,
    lon: float,
    data_inicio: str = Query(None, description="Start date in YYYY-MM-DD format"),
    data_fim: str = Query(None, description="End date in YYYY-MM-DD format")
):
    try:
        if not data_fim:
            data_fim = datetime.now().strftime('%Y-%m-%d')
        if not data_inicio:
            data_inicio = (datetime.now() - timedelta(days=365*50)).strftime('%Y-%m-%d')

        point = ee.Geometry.Point([lon, lat])

        def mask(image):
            qa = image.select('QA_PIXEL')
            cloud = qa.bitwiseAnd(1 << 5).eq(0)
            cloud_shadow = qa.bitwiseAnd(1 << 3).eq(0)
            return image.updateMask(cloud).updateMask(cloud_shadow)

        def calculate_ndvi(image):
            ndvi = image.normalizedDifference(['NIR', 'RED']).rename('NDVI')
            return image.addBands(ndvi)

        l4 = ee.ImageCollection('LANDSAT/LT04/C02/T1_L2').filterDate(data_inicio, data_fim).select(['SR_B3', 'SR_B4', 'QA_PIXEL'], ['RED', 'NIR', 'QA_PIXEL']).map(mask)
        l5 = ee.ImageCollection('LANDSAT/LT05/C02/T1_L2').filterDate(data_inicio, data_fim).select(['SR_B3', 'SR_B4', 'QA_PIXEL'], ['RED', 'NIR', 'QA_PIXEL']).map(mask)
        l7 = ee.ImageCollection('LANDSAT/LE07/C02/T1_L2').filterDate(data_inicio, data_fim).select(['SR_B3', 'SR_B4', 'QA_PIXEL'], ['RED', 'NIR', 'QA_PIXEL']).map(mask)
        l8 = ee.ImageCollection('LANDSAT/LC08/C02/T1_L2').filterDate(data_inicio, data_fim).select(['SR_B4', 'SR_B5', 'QA_PIXEL'], ['RED', 'NIR', 'QA_PIXEL']).map(mask)
        l9 = ee.ImageCollection('LANDSAT/LC09/C02/T1_L2').filterDate(data_inicio, data_fim).select(['SR_B4', 'SR_B5', 'QA_PIXEL'], ['RED', 'NIR', 'QA_PIXEL']).map(mask)

        collections = l4.merge(l5).merge(l7).merge(l8).merge(l9).filterBounds(point).map(calculate_ndvi)

        def get_ndvi_time_series(image):
            date = ee.Date(image.get('system:time_start')).format('YYYY-MM-dd')
            ndvi = image.select('NDVI').reduceRegion(
                ee.Reducer.mean(), point, 500
            ).get('NDVI')
            return ee.Feature(None, {'date': date, 'NDVI': ndvi})

        # Filter NDVI to remove extreme values
        ndvi_time_series = collections.map(get_ndvi_time_series).filter(ee.Filter.notNull(['NDVI'])).filter(ee.Filter.rangeContains('NDVI', 0, 1))

        ndvi_data = ndvi_time_series.reduceColumns(
            ee.Reducer.toList(2), ['date', 'NDVI']
        ).get('list').getInfo()

        ndvi_dates, ndvi_values = zip(*ndvi_data)

        # Remove duplicates and ensure unique dates
        ndvi_df = pd.DataFrame({'date': ndvi_dates, 'NDVI': ndvi_values})
        ndvi_df = ndvi_df.groupby('date').mean().reset_index()

        # Apply Savitzky-Golay filter
        def apply_savgol_filter(values, window_size=11, poly_order=2):
            if len(values) > window_size:
                return savgol_filter(values, window_length=window_size, polyorder=poly_order)
            return values

        ndvi_dates = ndvi_df['date'].tolist()
        ndvi_values = ndvi_df['NDVI'].tolist()
        ndvi_values_smoothed = apply_savgol_filter(np.array(ndvi_values))

        chirps = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(data_inicio, data_fim).filterBounds(point)

        def get_precipitation_time_series(image):
            date = ee.Date(image.get('system:time_start')).format('YYYY-MM-dd')
            precipitation = image.reduceRegion(
                ee.Reducer.mean(), point, 500
            ).get('precipitation')
            return ee.Feature(None, {'date': date, 'precipitation': precipitation})

        precip_time_series = chirps.map(get_precipitation_time_series).filter(ee.Filter.notNull(['precipitation']))

        precip_data = precip_time_series.reduceColumns(
            ee.Reducer.toList(2), ['date', 'precipitation']
        ).get('list').getInfo()

        precip_dates, precip_values = zip(*precip_data)

        plotly_data = [
            {
                'x': list(ndvi_dates),
                'y': list(ndvi_values_smoothed),
                'type': 'scatter',
                'mode': 'lines',
                'name': 'NDVI (Savgol)',
                'line': {'color': 'green'}
            },
            {
                'x': list(ndvi_dates),
                'y': list(ndvi_values),
                'type': 'scatter',
                'mode': 'markers',
                'name': 'NDVI (Original)',
                'marker': {'color': 'rgba(255, 165, 0, 0.2)'}  # Orange with 60% transparency
            },
            {
                'x': list(precip_dates),
                'y': list(precip_values),
                'type': 'bar',
                'name': 'Precipitation',
                'marker': {'color': 'blue'},
                'yaxis': 'y2'
            }
        ]

        return JSONResponse(content=plotly_data)

    except ee.EEException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching data from Earth Engine: {str(e)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )

@router.get("/sentinel2/{lat}/{lon}")
def timeseries_sentinel2(
    lat: float,
    lon: float,
    data_inicio: str = Query(None, description="Start date in YYYY-MM-DD format"),
    data_fim: str = Query(None, description="End date in YYYY-MM-DD format")
):
    try:
        if not data_fim:
            data_fim = datetime.now().strftime('%Y-%m-%d')
        if not data_inicio:
            data_inicio = (datetime.now() - timedelta(days=365*4.5)).strftime('%Y-%m-%d')

        point = ee.Geometry.Point([lon, lat])

        # Function to mask clouds using the QA60 band
        def maskS2clouds(image):
            qa = image.select('QA60')
            cloudBitMask = 1 << 10
            cirrusBitMask = 1 << 11
            mask = qa.bitwiseAnd(cloudBitMask).eq(0).And(qa.bitwiseAnd(cirrusBitMask).eq(0))
            return image.updateMask(mask)

        # Function to calculate and add an NDVI band
        def addNDVI(image):
            ndvi = image.normalizedDifference(['B8', 'B4']).rename('NDVI')
            return image.addBands(ndvi)

        # Load Sentinel-2 image collection
        s2 = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED') \
            .filterDate(data_inicio, data_fim) \
            .filterBounds(point) \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
            .map(maskS2clouds) \
            .map(addNDVI) \
            .filter(ee.Filter.notNull(['system:time_start']))

        # Create a time series of NDVI values
        def get_ndvi_time_series(image):
            date = ee.Date(image.get('system:time_start')).format('YYYY-MM-dd')
            ndvi = image.select('NDVI').reduceRegion(
                ee.Reducer.mean(), point, 500
            ).get('NDVI')
            return ee.Feature(None, {'date': date, 'NDVI': ndvi})

        ndvi_time_series = s2.map(get_ndvi_time_series).filter(ee.Filter.notNull(['NDVI']))

        ndvi_data_list = ndvi_time_series.reduceColumns(
            ee.Reducer.toList(2), ['date', 'NDVI']
        ).get('list').getInfo()

        if not ndvi_data_list:
            raise HTTPException(
                status_code=404,
                detail="No valid NDVI data found for the specified period and location."
            )

        ndvi_dates, ndvi_values = zip(*ndvi_data_list)

        ndvi_df = pd.DataFrame({'date': ndvi_dates, 'NDVI': ndvi_values})
        ndvi_df = ndvi_df.groupby('date').mean().reset_index()

        def apply_savgol_filter(values, window_size=11, poly_order=2):
            if len(values) > window_size:
                return savgol_filter(values, window_length=window_size, polyorder=poly_order).tolist()
            return values.tolist()

        ndvi_dates = ndvi_df['date'].tolist()
        ndvi_values = ndvi_df['NDVI'].tolist()
        ndvi_values_smoothed = apply_savgol_filter(np.array(ndvi_values))

        chirps = ee.ImageCollection('UCSB-CHG/CHIRPS/DAILY').filterDate(data_inicio, data_fim).filterBounds(point)

        def get_precipitation_time_series(image):
            date = ee.Date(image.get('system:time_start')).format('YYYY-MM-dd')
            precipitation = image.reduceRegion(
                ee.Reducer.mean(), point, 500
            ).get('precipitation')
            return ee.Feature(None, {'date': date, 'precipitation': precipitation})

        precip_time_series = chirps.map(get_precipitation_time_series).filter(ee.Filter.notNull(['precipitation']))

        precip_data_list = precip_time_series.reduceColumns(
            ee.Reducer.toList(2), ['date', 'precipitation']
        ).get('list').getInfo()

        precip_dates, precip_values = zip(*precip_data_list)

        plotly_data = [
            {
                'x': ndvi_dates,
                'y': ndvi_values_smoothed,
                'type': 'scatter',
                'mode': 'lines',
                'name': 'NDVI (Savgol)',
                'line': {'color': 'green'}
            },
            {
                'x': ndvi_dates,
                'y': ndvi_values,
                'type': 'scatter',
                'mode': 'markers',
                'name': 'NDVI (Original)',
                'marker': {'color': 'rgba(255, 165, 0, 0.2)'}  # Orange with 60% transparency
            },
            {
                'x': precip_dates,
                'y': precip_values,
                'type': 'bar',
                'name': 'Precipitation',
                'marker': {'color': 'blue'},
                'yaxis': 'y2'
            }
        ]

        return JSONResponse(content=plotly_data)

    except ee.EEException as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching data from Earth Engine: {str(e)}"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"An unexpected error occurred: {str(e)}"
        )