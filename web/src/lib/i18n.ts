/**
 * Copy for the page, in English and Spanish.
 *
 * This page is read by people deciding whether to keep the windows shut, on both
 * sides of a bilingual border community, so the Spanish is part of the product
 * rather than an afterthought. The strings below are a working draft and should
 * be reviewed by a native speaker before launch (see open question 3 in the plan).
 */

export type Lang = 'en' | 'es'

export interface Strings {
  title: string
  subtitle: string
  currentH2s: string
  conditions: string
  temperature: string
  humidity: string
  wind: string
  effluent: string
  effluentNote: string
  sevenDay: string
  sevenDayNote: string
  windowRange: string
  windowHistoric: string
  longTerm: string
  longTermNote: string
  window7: string
  window30: string
  window90: string
  hoursOver5: string
  hoursOver30: string
  noData: string
  stale: string
  staleWarning: string
  loading: string
  loadError: string
  asOf: string
  ppb: string
  layers: string
  layerStations: string
  layerWind: string
  windFrom: string
  windCalm: string
  windCalmLegend: string
  windLegend: string
  layerOcean: string
  whatThisMeans: string
  guidance: Record<'green' | 'yellow' | 'orange' | 'purple' | 'white', string>
  aboutTitle: string
  about: string
  dataFrom: string
  staleFootnote: (hours: number) => string
}

export const STRINGS: Record<Lang, Strings> = {
  en: {
    title: 'Tijuana River Valley — air and river conditions',
    subtitle: 'Hydrogen sulfide (H₂S), wind and river flow for Imperial Beach, Nestor and San Ysidro',
    currentH2s: 'Hydrogen sulfide right now',
    conditions: 'Weather and river',
    temperature: 'Temperature',
    humidity: 'Humidity',
    wind: 'Wind',
    effluent: 'Treatment plant discharge',
    effluentNote:
      'Plant discharge, not river flow. When the plant treats less, more sewage reaches the river and odour tends to rise.',
    sevenDay: 'The last 7 days',
    sevenDayNote: 'Drag the slider to move the map and the chart through the week.',
    windowRange: 'Showing',
    windowHistoric:
      'This is the most recent week of data published, not the week just gone — the monitoring feed is behind.',
    longTerm: 'Hours above the odour thresholds',
    longTermNote:
      'Hours per evening above 5 ppb (odour likely) and 30 ppb (strong odour) at each station.',
    window7: '7 days',
    window30: '30 days',
    window90: '90 days',
    hoursOver5: 'Hours above 5 ppb',
    hoursOver30: 'Hours above 30 ppb',
    noData: 'No data',
    stale: 'Out of date',
    staleWarning:
      'This reading is older than it should be. The monitoring feed has not updated recently — treat it as history, not as current conditions.',
    loading: 'Loading…',
    loadError: 'Could not load this data.',
    asOf: 'as of',
    ppb: 'ppb',
    layers: 'Layers',
    layerStations: 'Monitoring stations',
    layerWind: 'Wind',
    layerOcean: 'Ocean plume forecast',
    windFrom: 'from',
    windCalm: 'calm — air is pooling',
    windCalmLegend:
      'A dashed ring replaces the arrow when the air is still or stratified. There is no useful wind direction then, and it is exactly when H₂S builds up instead of blowing away.',
    windLegend:
      'The wind arrow points the way the air is moving; the bar sits on the side the wind comes from. The label repeats it in words.',
    whatThisMeans: 'What the numbers mean',
    guidance: {
      green: 'Below 5 ppb. Odour is possible but usually faint.',
      yellow: '5–30 ppb. Odour is likely and can be unpleasant.',
      orange: 'Above 30 ppb. Strong odour; headaches and nausea are commonly reported.',
      purple: 'Extremely high. Follow any guidance from public health authorities.',
      white: 'No reading available from this station.',
    },
    aboutTitle: 'About this map',
    about:
      'Readings come from three continuous San Diego APCD monitors. Weather is modelled, not measured. Everything shown here is published openly by the Resilient Collective data pipelines.',
    dataFrom: 'Data source',
    staleFootnote: (h) => `Readings older than ${h} h are marked out of date.`,
  },
  es: {
    title: 'Valle del Río Tijuana — condiciones del aire y del río',
    subtitle: 'Sulfuro de hidrógeno (H₂S), viento y caudal para Imperial Beach, Nestor y San Ysidro',
    currentH2s: 'Sulfuro de hidrógeno ahora',
    conditions: 'Clima y río',
    temperature: 'Temperatura',
    humidity: 'Humedad',
    wind: 'Viento',
    effluent: 'Descarga de la planta de tratamiento',
    effluentNote:
      'Descarga de la planta, no caudal del río. Cuando la planta trata menos, más aguas negras llegan al río y el olor suele aumentar.',
    sevenDay: 'Los últimos 7 días',
    sevenDayNote: 'Mueva el control para recorrer la semana en el mapa y en la gráfica.',
    windowRange: 'Mostrando',
    windowHistoric:
      'Esta es la semana más reciente de datos publicados, no la semana pasada — el monitoreo está atrasado.',
    longTerm: 'Horas por encima de los umbrales de olor',
    longTermNote:
      'Horas por noche por encima de 5 ppb (olor probable) y 30 ppb (olor fuerte) en cada estación.',
    window7: '7 días',
    window30: '30 días',
    window90: '90 días',
    hoursOver5: 'Horas sobre 5 ppb',
    hoursOver30: 'Horas sobre 30 ppb',
    noData: 'Sin datos',
    stale: 'Desactualizado',
    staleWarning:
      'Esta lectura es más antigua de lo debido. El sistema de monitoreo no se ha actualizado recientemente; tómelo como historial, no como condiciones actuales.',
    loading: 'Cargando…',
    loadError: 'No se pudieron cargar estos datos.',
    asOf: 'al',
    ppb: 'ppb',
    layers: 'Capas',
    layerStations: 'Estaciones de monitoreo',
    layerWind: 'Viento',
    layerOcean: 'Pronóstico de pluma oceánica',
    windFrom: 'del',
    windCalm: 'en calma — el aire se estanca',
    windCalmLegend:
      'Un círculo punteado reemplaza la flecha cuando el aire está quieto o estratificado. En ese caso no hay una dirección útil del viento, y es justo cuando el H₂S se acumula en vez de dispersarse.',
    windLegend:
      'La flecha del viento apunta hacia donde se mueve el aire; la barra marca el lado del que viene el viento. La etiqueta lo repite en palabras.',
    whatThisMeans: 'Qué significan las cifras',
    guidance: {
      green: 'Menos de 5 ppb. Puede haber olor, generalmente leve.',
      yellow: '5–30 ppb. Es probable que haya olor y puede ser desagradable.',
      orange: 'Más de 30 ppb. Olor fuerte; se reportan dolores de cabeza y náuseas.',
      purple: 'Extremadamente alto. Siga las indicaciones de las autoridades de salud.',
      white: 'No hay lectura disponible en esta estación.',
    },
    aboutTitle: 'Acerca de este mapa',
    about:
      'Las lecturas provienen de tres monitores continuos del APCD de San Diego. El viento es modelado, no medido. Todo lo aquí mostrado se publica abiertamente por los flujos de datos de Resilient Collective.',
    dataFrom: 'Fuente de datos',
    staleFootnote: (h) => `Las lecturas de más de ${h} h se marcan como desactualizadas.`,
  },
}
