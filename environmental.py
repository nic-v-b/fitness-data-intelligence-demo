"""Offline environmental observations and route-relative vector calculations."""

from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
import json
from math import asin, atan2, cos, degrees, isfinite, radians, sin, sqrt


EARTH_RADIUS_M = 6_371_008.8
WEATHER_FIELDS = {"air_temperature_c": (-100, 70), "wind_speed_mps": (0, 120), "wind_from_deg": (0, 360)}


def geographic_distance(a, b):
    lat_a, lat_b = radians(a[0]), radians(b[0])
    dlon = radians(b[1] - a[1])
    chord = sin((lat_b - lat_a) / 2)**2 + cos(lat_a) * cos(lat_b) * sin(dlon / 2)**2
    return 2 * EARTH_RADIUS_M * asin(sqrt(min(1, chord)))


def heading_deg(east_m, north_m):
    return degrees(atan2(east_m, north_m)) % 360 if east_m or north_m else None


def wind_components(speed_mps, from_deg, travel_deg):
    """Return positive headwind and positive wind pushing toward the rider's right."""
    if speed_mps == 0:
        return 0.0, 0.0
    if None in (speed_mps, from_deg, travel_deg):
        return None, None
    difference = radians(from_deg - travel_deg)
    return speed_mps * cos(difference), -speed_mps * sin(difference)


def finite(value, lo, hi):
    return (type(value) in (int, float) and lo <= value <= hi and isfinite(value))


def utc_seconds(value):
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.utcoffset() != timedelta(0):
        raise ValueError("Weather timestamps must be ISO 8601 UTC")
    return instant.timestamp()


def source_provenance(block, kinds):
    keys = ("provider", "product", "source_kind", "resolution", "reference")
    provenance = {key: block[key].strip() for key in keys}
    if not all(provenance.values()) or provenance["source_kind"] not in kinds:
        raise ValueError("Environmental provenance needs a provider, product, source kind, resolution and reference")
    return provenance


def observation_values(row, fields):
    values = {field: row.get(field) for field in fields}
    if not any(value is not None for value in values.values()) or any(
        value is not None and not finite(value, *fields[field]) for field, value in values.items()
    ):
        raise ValueError("Environmental row has no usable fields or contains an invalid value")
    return values


class Observations:
    def __init__(self, block, *, weather):
        kinds = {"station observation", "historical estimate"} if weather else {"terrain model"}
        provenance = source_provenance(block, kinds)
        self.radius_m = block["max_distance_m"]
        self.window_s = block["max_time_offset_s"] if weather else None
        if not finite(self.radius_m, 1, 100_000) or (weather and not finite(self.window_s, 1, 10_800)):
            raise ValueError("Invalid environmental spatial or temporal support")
        self.provenance = {**provenance, "max_distance_m": self.radius_m, "max_time_offset_s": self.window_s}
        self.rows = []
        seen = set()
        for row in block["points"]:
            lat_lon = row["latitude_deg"], row["longitude_deg"]
            if not finite(lat_lon[0], -90, 90) or not finite(lat_lon[1], -180, 180):
                raise ValueError("Invalid environmental coordinates")
            time = utc_seconds(row["time_utc"]) if weather else 0
            if (time, lat_lon) in seen:
                raise ValueError("Duplicate environmental observation location and time")
            seen.add((time, lat_lon))
            fields = WEATHER_FIELDS if weather else {"elevation_m": (-500, 9000)}
            values = observation_values(row, fields)
            self.rows.append((time, lat_lon, values))
        self.rows.sort(key=lambda row: row[:2])
        self.times = [row[0] for row in self.rows]

    def nearest(self, lat_lon, utc_s=None):
        if lat_lon is None or (self.window_s and utc_s is None):
            return {}
        if self.window_s:
            start = bisect_left(self.times, utc_s - self.window_s)
            finish = bisect_right(self.times, utc_s + self.window_s)
        else:
            start, finish = 0, len(self.rows)
        best, selected = float("inf"), {}
        for time, point, values in self.rows[start:finish]:
            distance = geographic_distance(lat_lon, point)
            if distance > self.radius_m:
                continue
            error = (distance / self.radius_m)**2
            if self.window_s:
                error += ((time - utc_s) / self.window_s)**2
            if error < best:
                best, selected = error, values
        return selected


class ActivityWeather:
    """Whole-activity summaries with reported coverage, indexed by FIT start."""

    def __init__(self, block):
        self.provenance = source_provenance(block, {"station observation", "historical estimate"})
        self.summaries = {}
        for row in block["summaries"]:
            time = utc_seconds(row["activity_start_utc"])
            count, anchors = row["source_sample_count"], row.get("spatial_anchor_count")
            if (time in self.summaries or type(count) is not int or count <= 0
                    or (anchors is not None and (type(anchors) is not int or not 0 < anchors <= count))):
                raise ValueError("Invalid activity weather summary identity or coverage")
            values = observation_values(row, WEATHER_FIELDS)
            counts = {field: row["field_sample_counts"].get(field, 0) for field in WEATHER_FIELDS}
            for field, samples in counts.items():
                if type(samples) is not int or not 0 <= samples <= count or bool(samples) != (values[field] is not None):
                    raise ValueError("Activity weather field counts must agree with summary values")
            self.summaries[time] = {**values, "source_sample_count": count,
                                    "spatial_anchor_count": anchors, "field_sample_counts": counts}


class Sources:
    def __init__(self, weather=None, terrain=None, activity_weather=None):
        self.weather, self.terrain = weather, terrain
        self.activity_weather = activity_weather

    @classmethod
    def load(cls, path, private_root):
        path = path.resolve()
        if not path.is_relative_to(private_root) or path.suffix.lower() != ".json":
            raise ValueError("Select environmental JSON inside the ignored private-data directory")
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
            if document["schema_version"] != 1 or not set(document) <= {
                "schema_version", "weather", "terrain", "activity_weather",
            }:
                raise ValueError
            return cls(Observations(document["weather"], weather=True) if "weather" in document else None,
                       Observations(document["terrain"], weather=False) if "terrain" in document else None,
                       ActivityWeather(document["activity_weather"]) if "activity_weather" in document else None)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError):
            raise ValueError("Invalid local environmental JSON. See docs/comparative-methods.md for the schema.") from None

    def provenance(self):
        return {name: source.provenance if source else None
                for name, source in (("weather", self.weather), ("terrain", self.terrain),
                                     ("activity_weather", self.activity_weather))}

    def activity_weather_at(self, start_utc_s):
        return self.activity_weather.summaries.get(start_utc_s) if self.activity_weather else None

    def weather_at(self, lat_lon, utc_s):
        return self.weather.nearest(lat_lon, utc_s) if self.weather else {}

    def terrain_at(self, lat_lon):
        return self.terrain.nearest(lat_lon).get("elevation_m") if self.terrain else None
