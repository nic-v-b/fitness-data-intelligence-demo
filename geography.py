"""Local-metre continuous route sections and directional polyline alignment."""

from bisect import bisect_left
from dataclasses import dataclass
from math import cos, floor, hypot, radians, sqrt


MATCH_STEP_M = 10
MATCH_TOLERANCE_M = 15
MATCH_MIN_M = 400
MAX_HEADING_DIFFERENCE_DEG = 35


def lerp(a, b, fraction):
    return a + (b - a) * fraction if a is not None and b is not None else None


class RoutePart:
    def __init__(self, samples, context):
        self.samples = samples
        self.context = context
        self.points = [(r["source"]["x_m"], r["source"]["y_m"]) for r in samples]
        self.distances = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.distances.append(self.distances[-1] + hypot(b[0] - a[0], b[1] - a[1]))
        self.length = self.distances[-1]

    def locate(self, distance):
        index = max(0, bisect_left(self.distances, distance) - 1)
        start, end = self.distances[index:index + 2]
        return index, (distance - start) / (end - start) if end > start else 0

    def point(self, distance):
        index, fraction = self.locate(distance)
        return tuple(lerp(a, b, fraction) for a, b in zip(self.points[index], self.points[index + 1]))

    def direction(self, distance):
        a = self.point(max(0, distance - 15))
        b = self.point(min(self.length, distance + 15))
        x, y = b[0] - a[0], b[1] - a[1]
        size = hypot(x, y)
        return (x / size, y / size) if size else (0, 0)

    def signal(self, index, name):
        if name == "temperature_c":
            return self.context[index].get(name)
        sample = self.samples[index]
        return sample["source"][name] if sample["quality"][name] == "valid" else None

    def value(self, distance, name):
        index, fraction = self.locate(distance)
        if fraction == 0:
            return self.signal(index, name)
        if fraction == 1:
            return self.signal(index + 1, name)
        return lerp(self.signal(index, name), self.signal(index + 1, name), fraction)

    def observation_position(self, distance):
        index, fraction = self.locate(distance)
        a, b = self.context[index:index + 2]
        lat_lon = None
        if a.get("lat_lon") is not None and b.get("lat_lon") is not None:
            lat_lon = tuple(lerp(start, end, fraction) for start, end in zip(a["lat_lon"], b["lat_lon"]))
        return lat_lon, lerp(a.get("utc_s"), b.get("utc_s"), fraction)

    def elapsed_at(self, distance):
        index, fraction = self.locate(distance)
        a, b = (sample["source"]["elapsed_s"] for sample in self.samples[index:index + 2])
        return lerp(a, b, fraction)

    def interval(self, start, finish):
        first, low = self.locate(start)
        last, high = self.locate(finish)
        totals = dict(moving_s=0.0, elapsed_s=0.0, heart_integral=0.0, heart_s=0.0,
                      device_temp_integral=0.0, device_temp_s=0.0)
        for edge in range(first, last + 1):
            f0, f1 = low if edge == first else 0, high if edge == last else 1
            a, b = (r["source"]["elapsed_s"] for r in self.samples[edge:edge + 2])
            dt = (b - a) * (f1 - f0)
            totals["elapsed_s"] += dt
            if self.context[edge + 1].get("stationary_pause_s") is not None:
                # A stationary bridge is retained only when its whole interval is a logged pause.
                continue
            totals["moving_s"] += dt
            for name, key in (("heart_rate_bpm", "heart"), ("temperature_c", "device_temp")):
                av, bv = self.signal(edge, name), self.signal(edge + 1, name)
                if av is not None and bv is not None:
                    totals[key + "_integral"] += (av + (bv - av) * (f0 + f1) / 2) * dt
                    totals[key + "_s"] += dt
        return totals

    def trace(self, step, offset=0):
        if step is None:
            return [[offset + distance, *point] for distance, point in zip(self.distances, self.points)]
        distances = [index * step for index in range(0, int(self.length / step) + 1)]
        if distances[-1] < self.length:
            distances.append(self.length)
        return [[offset + distance, *self.point(distance)] for distance in distances]


def route_parts(activity, context=None):
    samples = activity["samples"]
    if context is None:
        context = [{}] * len(samples)
    parts = []
    start = 0
    for index, (sample, facts) in enumerate(zip(samples, context)):
        source = sample["source"]
        gap = source["x_m"] is None or source["y_m"] is None
        prev = samples[index - 1]["source"]
        stationary_break = (index > 0 and facts.get("stationary_pause_s") is not None
                            and facts["stationary_pause_s"] == source["elapsed_s"] - prev["elapsed_s"])
        if gap or (sample.get("route_break_before") and not stationary_break):
            if index - start >= 2:
                parts.append(RoutePart(samples[start:index], context[start:index]))
            start = index + int(gap)
    if len(samples) - start >= 2:
        parts.append(RoutePart(samples[start:], context[start:]))
    return [part for part in parts if part.length > 0]


@dataclass
class Link:
    a_m: float
    b_m: float
    separation_m: float
    steps: int
    error: float
    previous: "Link | None" = None


def spatial_edges(part):
    """Index B's individual edges in a tolerance-sized grid."""
    cell = MATCH_TOLERANCE_M
    grid = {}
    for i, (a, b) in enumerate(zip(part.points, part.points[1:])):
        length = part.distances[i + 1] - part.distances[i]
        if not length:
            continue
        direction = part.direction(part.distances[i] + length / 2)
        edge = (a, b, part.distances[i], length, direction)
        for x in range(floor(min(a[0], b[0]) / cell), floor(max(a[0], b[0]) / cell) + 1):
            for y in range(floor(min(a[1], b[1]) / cell), floor(max(a[1], b[1]) / cell) + 1):
                grid.setdefault((x, y), []).append(edge)
    return grid


def projections(point, direction, grid):
    radius = MATCH_TOLERANCE_M
    x, y = point
    min_dot = cos(radians(MAX_HEADING_DIFFERENCE_DEG))
    candidates = {}
    for col in range(floor(x / radius) - 1, floor(x / radius) + 2):
        for row in range(floor(y / radius) - 1, floor(y / radius) + 2):
            for a, b, start, length, tangent in grid.get((col, row), ()):
                if sum(u * v for u, v in zip(direction, tangent)) < min_dot:
                    continue
                dx, dy = b[0] - a[0], b[1] - a[1]
                fraction = ((x - a[0]) * dx + (y - a[1]) * dy) / length**2
                fraction = max(0, min(1, fraction))
                error = (x - (a[0] + fraction * dx))**2 + (y - (a[1] + fraction * dy))**2
                if error <= radius**2:
                    distance = start + fraction * length
                    candidates[distance] = min(error, candidates.get(distance, error))
    return sorted(candidates.items())


def link_pair(a, grid):
    previous = []
    longest = None
    for a_m in range(0, int(a.length) + 1, MATCH_STEP_M):
        options = []
        for b_m, error in projections(a.point(a_m), a.direction(a_m), grid):
            prior = max((link for link in previous if 0.5 * MATCH_STEP_M <= b_m - link.b_m <= 1.5 * MATCH_STEP_M),
                        key=lambda link: (link.steps, -link.error), default=None)
            link = Link(a_m, b_m, sqrt(error), 1, error, prior)
            if prior:
                link.steps += prior.steps
                link.error += prior.error
            if longest is None or (link.steps, -link.error) > (longest.steps, -longest.error):
                longest = link
            options.append(link)
        previous = options
    return longest


def match_route(a_parts, b_parts):
    """Find the longest contiguous same-direction match, breaking ties by separation."""
    best = None
    for b in b_parts:
        if b.length < MATCH_MIN_M * .5:
            continue
        grid = spatial_edges(b)
        for a in a_parts:
            if a.length < MATCH_MIN_M:
                continue
            link = link_pair(a, grid)
            if link is not None and (best is None or (link.steps, -link.error) > (best[2].steps, -best[2].error)):
                best = a, b, link
    if best is None or (best[2].steps - 1) * MATCH_STEP_M < MATCH_MIN_M:
        return None
    a, b, link = best
    chain = []
    while link is not None:
        chain.append(link)
        link = link.previous
    return a, b, chain[::-1]
