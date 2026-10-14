/**
 * Countries for registration: choosing one fills in the phone calling code (to read national phone numbers) and a default
 * currency. Plain reference data, not behaviour: nothing in the platform treats any country specially. Each entry is
 * [ISO 3166 code, name, calling code (digits, no +), ISO 4217 currency of the country].
 * Countries that share a calling code (the +1 numbering plan) share it here.
 */
export type Country = { code: string; name: string; calling: string; currency: string; zone: string };

/**
 * The main IANA time zone of each country (for countries with several, the most populated): a default for the business's
 * time zone at registration, which the owner can change later in Settings. Reference data, not behaviour.
 */
const ZONES: Readonly<Record<string, string>> = {
  AE: "Asia/Dubai", AF: "Asia/Kabul", AL: "Europe/Tirane",
  AM: "Asia/Yerevan", AO: "Africa/Luanda", AR: "America/Argentina/Buenos_Aires",
  AT: "Europe/Vienna", AU: "Australia/Sydney", AZ: "Asia/Baku",
  BA: "Europe/Sarajevo", BB: "America/Barbados", BD: "Asia/Dhaka",
  BE: "Europe/Brussels", BF: "Africa/Ouagadougou", BG: "Europe/Sofia",
  BH: "Asia/Bahrain", BI: "Africa/Bujumbura", BJ: "Africa/Porto-Novo",
  BN: "Asia/Brunei", BO: "America/La_Paz", BR: "America/Sao_Paulo",
  BS: "America/Nassau", BT: "Asia/Thimphu", BW: "Africa/Gaborone",
  BY: "Europe/Minsk", BZ: "America/Belize", CA: "America/Toronto",
  CD: "Africa/Kinshasa", CF: "Africa/Bangui", CG: "Africa/Brazzaville",
  CH: "Europe/Zurich", CI: "Africa/Abidjan", CL: "America/Santiago",
  CM: "Africa/Douala", CN: "Asia/Shanghai", CO: "America/Bogota",
  CR: "America/Costa_Rica", CU: "America/Havana", CV: "Atlantic/Cape_Verde",
  CY: "Asia/Nicosia", CZ: "Europe/Prague", DE: "Europe/Berlin",
  DJ: "Africa/Djibouti", DK: "Europe/Copenhagen", DO: "America/Santo_Domingo",
  DZ: "Africa/Algiers", EC: "America/Guayaquil", EE: "Europe/Tallinn",
  EG: "Africa/Cairo", ER: "Africa/Asmara", ES: "Europe/Madrid",
  ET: "Africa/Addis_Ababa", FI: "Europe/Helsinki", FJ: "Pacific/Fiji",
  FR: "Europe/Paris", GA: "Africa/Libreville", GB: "Europe/London",
  GE: "Asia/Tbilisi", GH: "Africa/Accra", GM: "Africa/Banjul",
  GN: "Africa/Conakry", GQ: "Africa/Malabo", GR: "Europe/Athens",
  GT: "America/Guatemala", GW: "Africa/Bissau", GY: "America/Guyana",
  HK: "Asia/Hong_Kong", HN: "America/Tegucigalpa", HR: "Europe/Zagreb",
  HT: "America/Port-au-Prince", HU: "Europe/Budapest", ID: "Asia/Jakarta",
  IE: "Europe/Dublin", IL: "Asia/Jerusalem", IN: "Asia/Kolkata",
  IQ: "Asia/Baghdad", IR: "Asia/Tehran", IS: "Atlantic/Reykjavik",
  IT: "Europe/Rome", JM: "America/Jamaica", JO: "Asia/Amman",
  JP: "Asia/Tokyo", KE: "Africa/Nairobi", KG: "Asia/Bishkek",
  KH: "Asia/Phnom_Penh", KM: "Indian/Comoro", KR: "Asia/Seoul",
  KW: "Asia/Kuwait", KZ: "Asia/Almaty", LA: "Asia/Vientiane",
  LB: "Asia/Beirut", LI: "Europe/Vaduz", LK: "Asia/Colombo",
  LR: "Africa/Monrovia", LS: "Africa/Maseru", LT: "Europe/Vilnius",
  LU: "Europe/Luxembourg", LV: "Europe/Riga", LY: "Africa/Tripoli",
  MA: "Africa/Casablanca", MD: "Europe/Chisinau", ME: "Europe/Podgorica",
  MG: "Indian/Antananarivo", MK: "Europe/Skopje", ML: "Africa/Bamako",
  MM: "Asia/Yangon", MN: "Asia/Ulaanbaatar", MO: "Asia/Macau",
  MR: "Africa/Nouakchott", MT: "Europe/Malta", MU: "Indian/Mauritius",
  MV: "Indian/Maldives", MW: "Africa/Blantyre", MX: "America/Mexico_City",
  MY: "Asia/Kuala_Lumpur", MZ: "Africa/Maputo", NA: "Africa/Windhoek",
  NE: "Africa/Niamey", NG: "Africa/Lagos", NI: "America/Managua",
  NL: "Europe/Amsterdam", NO: "Europe/Oslo", NP: "Asia/Kathmandu",
  NZ: "Pacific/Auckland", OM: "Asia/Muscat", PA: "America/Panama",
  PE: "America/Lima", PG: "Pacific/Port_Moresby", PH: "Asia/Manila",
  PK: "Asia/Karachi", PL: "Europe/Warsaw", PS: "Asia/Gaza",
  PT: "Europe/Lisbon", PY: "America/Asuncion", QA: "Asia/Qatar",
  RO: "Europe/Bucharest", RS: "Europe/Belgrade", RU: "Europe/Moscow",
  RW: "Africa/Kigali", SA: "Asia/Riyadh", SB: "Pacific/Guadalcanal",
  SC: "Indian/Mahe", SD: "Africa/Khartoum", SE: "Europe/Stockholm",
  SG: "Asia/Singapore", SI: "Europe/Ljubljana", SK: "Europe/Bratislava",
  SL: "Africa/Freetown", SN: "Africa/Dakar", SO: "Africa/Mogadishu",
  SR: "America/Paramaribo", SS: "Africa/Juba", ST: "Africa/Sao_Tome",
  SV: "America/El_Salvador", SY: "Asia/Damascus", SZ: "Africa/Mbabane",
  TD: "Africa/Ndjamena", TG: "Africa/Lome", TH: "Asia/Bangkok",
  TJ: "Asia/Dushanbe", TL: "Asia/Dili", TM: "Asia/Ashgabat",
  TN: "Africa/Tunis", TO: "Pacific/Tongatapu", TR: "Europe/Istanbul",
  TT: "America/Port_of_Spain", TW: "Asia/Taipei", TZ: "Africa/Dar_es_Salaam",
  UA: "Europe/Kyiv", UG: "Africa/Kampala", US: "America/New_York",
  UY: "America/Montevideo", UZ: "Asia/Tashkent", VE: "America/Caracas",
  VN: "Asia/Ho_Chi_Minh", VU: "Pacific/Efate", WS: "Pacific/Apia",
  YE: "Asia/Aden", ZA: "Africa/Johannesburg", ZM: "Africa/Lusaka",
  ZW: "Africa/Harare",
};

const DATA: readonly (readonly [string, string, string, string])[] = [
  // Africa
  ["DZ", "Algeria", "213", "DZD"], ["AO", "Angola", "244", "AOA"], ["BJ", "Benin", "229", "XOF"],
  ["BW", "Botswana", "267", "BWP"], ["BF", "Burkina Faso", "226", "XOF"], ["BI", "Burundi", "257", "BIF"],
  ["CM", "Cameroon", "237", "XAF"], ["CV", "Cabo Verde", "238", "CVE"], ["CF", "Central African Republic", "236", "XAF"],
  ["TD", "Chad", "235", "XAF"], ["KM", "Comoros", "269", "KMF"], ["CG", "Congo", "242", "XAF"],
  ["CD", "Congo (Democratic Republic)", "243", "CDF"], ["CI", "Côte d'Ivoire", "225", "XOF"], ["DJ", "Djibouti", "253", "DJF"],
  ["EG", "Egypt", "20", "EGP"], ["GQ", "Equatorial Guinea", "240", "XAF"], ["ER", "Eritrea", "291", "ERN"],
  ["SZ", "Eswatini", "268", "SZL"], ["ET", "Ethiopia", "251", "ETB"], ["GA", "Gabon", "241", "XAF"],
  ["GM", "Gambia", "220", "GMD"], ["GH", "Ghana", "233", "GHS"], ["GN", "Guinea", "224", "GNF"],
  ["GW", "Guinea-Bissau", "245", "XOF"], ["KE", "Kenya", "254", "KES"], ["LS", "Lesotho", "266", "LSL"],
  ["LR", "Liberia", "231", "LRD"], ["LY", "Libya", "218", "LYD"], ["MG", "Madagascar", "261", "MGA"],
  ["MW", "Malawi", "265", "MWK"], ["ML", "Mali", "223", "XOF"], ["MR", "Mauritania", "222", "MRU"],
  ["MU", "Mauritius", "230", "MUR"], ["MA", "Morocco", "212", "MAD"], ["MZ", "Mozambique", "258", "MZN"],
  ["NA", "Namibia", "264", "NAD"], ["NE", "Niger", "227", "XOF"], ["NG", "Nigeria", "234", "NGN"],
  ["RW", "Rwanda", "250", "RWF"], ["ST", "São Tomé and Príncipe", "239", "STN"], ["SN", "Senegal", "221", "XOF"],
  ["SC", "Seychelles", "248", "SCR"], ["SL", "Sierra Leone", "232", "SLE"], ["SO", "Somalia", "252", "SOS"],
  ["ZA", "South Africa", "27", "ZAR"], ["SS", "South Sudan", "211", "SSP"], ["SD", "Sudan", "249", "SDG"],
  ["TZ", "Tanzania", "255", "TZS"], ["TG", "Togo", "228", "XOF"], ["TN", "Tunisia", "216", "TND"],
  ["UG", "Uganda", "256", "UGX"], ["ZM", "Zambia", "260", "ZMW"], ["ZW", "Zimbabwe", "263", "ZWG"],
  // Americas
  ["US", "United States", "1", "USD"], ["CA", "Canada", "1", "CAD"], ["MX", "Mexico", "52", "MXN"],
  ["GT", "Guatemala", "502", "GTQ"], ["BZ", "Belize", "501", "BZD"], ["SV", "El Salvador", "503", "USD"],
  ["HN", "Honduras", "504", "HNL"], ["NI", "Nicaragua", "505", "NIO"], ["CR", "Costa Rica", "506", "CRC"],
  ["PA", "Panama", "507", "PAB"], ["CU", "Cuba", "53", "CUP"], ["DO", "Dominican Republic", "1", "DOP"],
  ["JM", "Jamaica", "1", "JMD"], ["TT", "Trinidad and Tobago", "1", "TTD"], ["BS", "Bahamas", "1", "BSD"],
  ["BB", "Barbados", "1", "BBD"], ["HT", "Haiti", "509", "HTG"], ["CO", "Colombia", "57", "COP"],
  ["VE", "Venezuela", "58", "VES"], ["EC", "Ecuador", "593", "USD"], ["PE", "Peru", "51", "PEN"],
  ["BO", "Bolivia", "591", "BOB"], ["CL", "Chile", "56", "CLP"], ["AR", "Argentina", "54", "ARS"],
  ["UY", "Uruguay", "598", "UYU"], ["PY", "Paraguay", "595", "PYG"], ["BR", "Brazil", "55", "BRL"],
  ["GY", "Guyana", "592", "GYD"], ["SR", "Suriname", "597", "SRD"],
  // Europe
  ["GB", "United Kingdom", "44", "GBP"], ["IE", "Ireland", "353", "EUR"], ["FR", "France", "33", "EUR"],
  ["DE", "Germany", "49", "EUR"], ["ES", "Spain", "34", "EUR"], ["PT", "Portugal", "351", "EUR"],
  ["IT", "Italy", "39", "EUR"], ["NL", "Netherlands", "31", "EUR"], ["BE", "Belgium", "32", "EUR"],
  ["LU", "Luxembourg", "352", "EUR"], ["AT", "Austria", "43", "EUR"], ["CH", "Switzerland", "41", "CHF"],
  ["LI", "Liechtenstein", "423", "CHF"], ["DK", "Denmark", "45", "DKK"], ["SE", "Sweden", "46", "SEK"],
  ["NO", "Norway", "47", "NOK"], ["FI", "Finland", "358", "EUR"], ["IS", "Iceland", "354", "ISK"],
  ["PL", "Poland", "48", "PLN"], ["CZ", "Czechia", "420", "CZK"], ["SK", "Slovakia", "421", "EUR"],
  ["HU", "Hungary", "36", "HUF"], ["RO", "Romania", "40", "RON"], ["BG", "Bulgaria", "359", "EUR"],
  ["HR", "Croatia", "385", "EUR"], ["SI", "Slovenia", "386", "EUR"], ["RS", "Serbia", "381", "RSD"],
  ["BA", "Bosnia and Herzegovina", "387", "BAM"], ["ME", "Montenegro", "382", "EUR"], ["MK", "North Macedonia", "389", "MKD"],
  ["AL", "Albania", "355", "ALL"], ["GR", "Greece", "30", "EUR"], ["CY", "Cyprus", "357", "EUR"],
  ["MT", "Malta", "356", "EUR"], ["EE", "Estonia", "372", "EUR"], ["LV", "Latvia", "371", "EUR"],
  ["LT", "Lithuania", "370", "EUR"], ["UA", "Ukraine", "380", "UAH"], ["MD", "Moldova", "373", "MDL"],
  ["BY", "Belarus", "375", "BYN"], ["RU", "Russia", "7", "RUB"], ["TR", "Türkiye", "90", "TRY"],
  ["GE", "Georgia", "995", "GEL"], ["AM", "Armenia", "374", "AMD"], ["AZ", "Azerbaijan", "994", "AZN"],
  // Middle East
  ["AE", "United Arab Emirates", "971", "AED"], ["SA", "Saudi Arabia", "966", "SAR"], ["QA", "Qatar", "974", "QAR"],
  ["KW", "Kuwait", "965", "KWD"], ["BH", "Bahrain", "973", "BHD"], ["OM", "Oman", "968", "OMR"],
  ["JO", "Jordan", "962", "JOD"], ["LB", "Lebanon", "961", "LBP"], ["IL", "Israel", "972", "ILS"],
  ["IQ", "Iraq", "964", "IQD"], ["IR", "Iran", "98", "IRR"], ["SY", "Syria", "963", "SYP"],
  ["YE", "Yemen", "967", "YER"], ["PS", "Palestine", "970", "ILS"],
  // Asia
  ["IN", "India", "91", "INR"], ["PK", "Pakistan", "92", "PKR"], ["BD", "Bangladesh", "880", "BDT"],
  ["LK", "Sri Lanka", "94", "LKR"], ["NP", "Nepal", "977", "NPR"], ["BT", "Bhutan", "975", "BTN"],
  ["MV", "Maldives", "960", "MVR"], ["AF", "Afghanistan", "93", "AFN"], ["CN", "China", "86", "CNY"],
  ["HK", "Hong Kong", "852", "HKD"], ["MO", "Macao", "853", "MOP"], ["TW", "Taiwan", "886", "TWD"],
  ["JP", "Japan", "81", "JPY"], ["KR", "South Korea", "82", "KRW"], ["MN", "Mongolia", "976", "MNT"],
  ["SG", "Singapore", "65", "SGD"], ["MY", "Malaysia", "60", "MYR"], ["TH", "Thailand", "66", "THB"],
  ["VN", "Vietnam", "84", "VND"], ["KH", "Cambodia", "855", "KHR"], ["LA", "Laos", "856", "LAK"],
  ["MM", "Myanmar", "95", "MMK"], ["ID", "Indonesia", "62", "IDR"], ["PH", "Philippines", "63", "PHP"],
  ["BN", "Brunei", "673", "BND"], ["TL", "Timor-Leste", "670", "USD"], ["KZ", "Kazakhstan", "7", "KZT"],
  ["UZ", "Uzbekistan", "998", "UZS"], ["KG", "Kyrgyzstan", "996", "KGS"], ["TJ", "Tajikistan", "992", "TJS"],
  ["TM", "Turkmenistan", "993", "TMT"],
  // Oceania
  ["AU", "Australia", "61", "AUD"], ["NZ", "New Zealand", "64", "NZD"], ["PG", "Papua New Guinea", "675", "PGK"],
  ["FJ", "Fiji", "679", "FJD"], ["WS", "Samoa", "685", "WST"], ["TO", "Tonga", "676", "TOP"],
  ["VU", "Vanuatu", "678", "VUV"], ["SB", "Solomon Islands", "677", "SBD"],
];

export const COUNTRIES: readonly Country[] = DATA.map(([code, name, calling, currency]) => ({ code, name, calling, currency, zone: ZONES[code] ?? "UTC" }))
  .sort((a, b) => a.name.localeCompare(b.name));

export const CURRENCIES: readonly string[] = [...new Set(COUNTRIES.map((c) => c.currency))].sort();

export function countryByCode(code: string): Country | undefined {
  return COUNTRIES.find((c) => c.code === code);
}
