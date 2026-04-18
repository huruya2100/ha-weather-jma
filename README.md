# ha-weather-jma

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
- Binary sensors for advisories, warnings, danger warnings, and emergency warnings
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
By default, config-only sensors such as forecast area and observation station
are not created.

### Created entities

After setup, the integration creates:

- 1 weather entity
- Sensor entities such as forecast area, observation station, report datetime,
  publishing office, today's precipitation probability, tomorrow's
  precipitation probability, alert summary, and alert max level
- Binary sensor entities for each enabled warning/advisory level

### Data sources

- Forecast and area definitions: JMA `bosai` JSON endpoints
- Observation data: JMA AMeDAS JSON endpoints
- Warning data: JMA XML warning feeds and warning XML documents

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
