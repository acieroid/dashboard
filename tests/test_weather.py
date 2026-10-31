from homelab_status.weather import describe_weather, parse_forecast


def test_parse_brussels_forecast() -> None:
    forecast = parse_forecast(
        {
            "current": {
                "temperature_2m": 9.4,
                "apparent_temperature": 7.1,
                "weather_code": 2,
            },
            "daily": {
                "weather_code": [61],
                "temperature_2m_min": [5.2],
                "temperature_2m_max": [11.8],
                "precipitation_probability_max": [70],
            },
        },
        "Brussels",
    )

    assert forecast == {
        "location": "Brussels",
        "temperature_c": 9.4,
        "apparent_temperature_c": 7.1,
        "condition": "Partly cloudy",
        "forecast_condition": "Rain",
        "minimum_c": 5.2,
        "maximum_c": 11.8,
        "precipitation_probability": 70,
        "forecast": [],
    }


def test_weather_code_fallback() -> None:
    assert describe_weather(0) == "Clear"
    assert describe_weather(999) == "Mixed"
