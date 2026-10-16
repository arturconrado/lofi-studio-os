"""Versioned scene registry: camera, props, weather and light per scenario.

Objects are listed only when visible in the reviewed source. A prop that is not
listed cannot be used by an action; adding one requires a reviewed new base.
"""
from copy import deepcopy

LIGHT = {
    'sunset_to_night': [{'minute':0,'night':0,'city_lights':0}, {'minute':15,'night':1,'city_lights':1},
                        {'minute':48,'night':1,'city_lights':1}, {'minute':50,'night':1,'city_lights':.5},
                        {'minute':60,'night':1,'city_lights':.5}],
    'night_stars': [{'minute':0,'night':0,'stars':0}, {'minute':15,'night':1,'stars':1},
                    {'minute':60,'night':1,'stars':1}],
    'night_to_dawn': [{'minute':0,'sky_light':0,'city_lights':1}, {'minute':50,'sky_light':.05,'city_lights':.5},
                      {'minute':60,'sky_light':1,'city_lights':0}],
    # Approved hour visuals already contain their light; neutral keyframes add nothing.
    'static': [{'minute':0}, {'minute':60}],
    'day_to_dusk': [{'minute':0,'night':0,'city_lights':0}, {'minute':40,'night':.6,'city_lights':1},
                    {'minute':60,'night':.6,'city_lights':1}],
}

SCENES = {
    'city_sunset': {'label':'Janela · cidade ao entardecer','camera':'locked_reference_frame','approved_pilot_id':None,
        'weather':'clear','weather_baked':False,'allowed_weather':['clear','rain','snow','fog'],
        'period':'sunset_to_night','allowed_periods':['sunset_to_night','static'],
        'props':['phone','cat','cushion'],'objects':{},'requires_lights_region':True,'stars':False},
    'mountain_stars': {'label':'Janela · montanhas e estrelas','camera':'locked_reference_frame','approved_pilot_id':None,
        'weather':'clear','weather_baked':False,'allowed_weather':['clear','snow','fog'],
        'period':'night_stars','allowed_periods':['night_stars','static'],
        'props':['phone','cat','cushion'],'objects':{},'requires_lights_region':False,'stars':True},
    'balcony_dawn': {'label':'Varanda · cidade ao amanhecer','camera':'locked_reference_frame','approved_pilot_id':None,
        'weather':'clear','weather_baked':False,'allowed_weather':['clear','rain','fog'],
        'period':'night_to_dawn','allowed_periods':['night_to_dawn','static'],
        'props':['phone','cat','cushion'],'objects':{},'requires_lights_region':True,'stars':False},
    # Approved one-hour baselines (owner confirmation 2026-10-15). No phone or cushion is visible.
    'snowy_night_studio': {'label':'Snowy Night Studio · lareira e neve','camera':'locked_reference_frame',
        'approved_pilot_id':'1192acca-4cea-5d5b-9cf2-0a436909fc0e',
        'weather':'snow','weather_baked':True,'allowed_weather':['snow'],
        'period':'static','allowed_periods':['static'],
        'props':['cat','mug'],'objects':{'fireplace':{'initial':'on'}},'requires_lights_region':False,'stars':False},
    'greenhouse_rain_study': {'label':'Greenhouse Rain Study · estufa com chuva','camera':'locked_reference_frame',
        'approved_pilot_id':'013eb0ef-06e3-578f-a9f8-a49532b5478b',
        'weather':'rain','weather_baked':True,'allowed_weather':['rain'],
        'period':'static','allowed_periods':['static','day_to_dusk'],
        'props':['cat','mug'],'objects':{'string_lights':{'initial':'on'}},'requires_lights_region':False,'stars':False},
    'autumn_bookshop': {'label':'Autumn Bookshop Coding · livraria e chuva','camera':'locked_reference_frame',
        'approved_pilot_id':'277ef275-73f0-53fb-ba14-9046186151fd',
        'weather':'rain','weather_baked':True,'allowed_weather':['rain'],
        'period':'static','allowed_periods':['static','day_to_dusk'],
        'props':['cat','mug'],'objects':{'lamp':{'initial':'on'}},'requires_lights_region':False,'stars':False},
}
LEGACY = ('city_sunset','mountain_stars','balcony_dawn')


def scene(name):
    if name not in SCENES:raise ValueError('Cenário desconhecido')
    return deepcopy(SCENES[name])


def resolve(spec):
    """Effective weather/period after validating the per-episode choice."""
    s=scene(spec.scenario)
    weather=s['weather'] if spec.weather=='scene_default' else spec.weather
    period=s['period'] if spec.time_of_day=='scene_default' else spec.time_of_day
    if weather not in s['allowed_weather']:raise ValueError(f'Clima {weather} indisponível em {spec.scenario}')
    if period not in s['allowed_periods']:raise ValueError(f'Período {period} indisponível em {spec.scenario}')
    overlay=None
    if weather in ('rain','snow','fog') and not s['weather_baked']:
        overlay={'type':weather,'intensity':.5 if spec.precipitation_intensity is None else spec.precipitation_intensity}
    return {'weather':weather,'period':period,'keyframes':deepcopy(LIGHT[period]),'overlay':overlay,
            'props':s['props'],'objects':s['objects'],'stars':s['stars'],'approved_pilot_id':s['approved_pilot_id'],
            'requires_lights_region':s['requires_lights_region'],'cushion':'cushion' in s['props']}


def catalog():
    return {name:{k:v for k,v in s.items()} for name,s in SCENES.items()}
