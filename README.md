# ha-weather-jma

[![Pytest](https://github.com/huruya2100/ha-weather-jma/actions/workflows/auto-test.yml/badge.svg?branch=main)](https://github.com/huruya2100/ha-weather-jma/actions/workflows/auto-test.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://www.hacs.xyz/docs/faq/custom_repositories/)

Unofficial Home Assistant custom integration using weather data published by the
Japan Meteorological Agency.

気象庁が公開している気象データを利用する、非公式の Home Assistant
カスタム統合です。

This project is not provided by, affiliated with, or endorsed by the Japan
Meteorological Agency.

本プロジェクトは気象庁が提供・運営・公認するものではありません。

### Features

- Weather entity backed by JMA forecast and AMeDAS observation data
- Sensors for forecast area, observation station, report time, publishing office,
  precipitation probability, and warning summary
- Binary sensors for advisories, warnings, urgent warnings, and emergency warnings
- Config flow support from the Home Assistant UI

### Installation

#### Via HACS

1. Open HACS.
2. Open the top-right menu and choose `Custom repositories`.
3. Add the repository URL and select `Integration`.
4. Install `ha-weather-jma`.
5. Restart Home Assistant.
6. Open `Settings` -> `Devices & Services`.
7. Click `Add Integration` and search for `ha-weather-jma`.

#### Manual installation

1. Copy `custom_components/ha_weather_jma` into your Home Assistant config directory:
   `<config>/custom_components/ha_weather_jma/`
2. Restart Home Assistant.
3. Open `Settings` -> `Devices & Services`.
4. Click `Add Integration` and search for `ha-weather-jma`.

### Configuration

The integration is configured from the UI. During setup, you will be asked to
select:

1. Broad region
2. Forecast area
3. Observation station
4. Warning area
5. Display name
6. Update interval in minutes
7. Warning levels to generate
8. Additional entity groups to create

The update interval range is 5 to 60 minutes, and the default is 10 minutes.
Location and update metadata are exposed on the management control entity
instead of separate sensors.

### Created entities

After setup, the integration creates:

- 1 weather entity
- Sensor entities such as report datetime, publishing office, today's
  precipitation probability, tomorrow's precipitation probability, alert
  summary, and alert max level
- Binary sensor entities for each enabled warning/advisory level
- Management entities for force refresh, read-only forecast/observation/warning
  location metadata, and refresh timestamps

### Data sources

- Forecast and area definitions: JMA `bosai` JSON endpoints
- Observation data: JMA AMeDAS JSON endpoints
- Warning data: JMA XML warning feeds and warning XML documents

### Forecast area and temperature coverage

JMA forecast JSON does not always publish every data type at the same geographic
granularity.

- Short-term forecasts are usually published for the selected forecast area.
- Weekly weather and precipitation probability may be published only for a
  broader representative area. During new setup, the integration shows the
  representative area and asks whether its weekly forecast should be used.
  Declining keeps the short-term forecast and excludes all weekly weather,
  precipitation, and temperature data.
  For example, `190010` 中・西部 may receive weekly weather from `190000`
  山梨県, and `474020` 与那国島地方 may receive weekly weather from `474000`
  八重山地方.
- Weekly temperatures are observation-station based. They are used only when JMA
  publishes values for the selected observation station. The integration does
  not substitute a different representative station, because that would display
  another location's temperature as if it belonged to the selected location. For
  example, if JMA publishes weekly temperatures for `94081` 石垣島 only, `94017`
  与那国島 remains without weekly temperature values.

The report datetime sensor exposes `daily_forecast_coverage` attributes showing
which area supplied weather/precipitation and which station supplied
temperature for each forecast date. The read-only management sensors also expose
the weekly weather and temperature selection policies as attributes.

Forecast and warning choices include the prefecture as well as the publishing
office. The default device name also combines the prefecture and forecast area,
for example `北海道 北部`; it remains editable during setup. Existing device
names are not renamed automatically.

### Development

The repository includes a lightweight regression test suite that runs without a
full Home Assistant installation by using local stubs.

```bash
uv run pytest
uv run ruff check .
```

Current local verification:

- `uv run pytest`
- `uv run ruff check .`
- `uv run python -m compileall custom_components tests`

### Warning implementation

Warning handling is XML-first.

- The integration resolves warning documents from the JMA XML `Atom` feeds
  published on the 2026 warning-system technical information page:
  https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/tech-info/index.html
- It reads the latest warning XML for the configured office and normalizes
  `VPWW53` plus the 2026 warning products `VPWW55` to `VPWW61`.
- Runtime warning parsing no longer depends on the legacy `bosai/warning/*.json`
  endpoint.
