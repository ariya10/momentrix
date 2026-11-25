"""Translate sampled anonymous detections into bounded, source-time FFmpeg expressions."""
from math import isfinite
from statistics import median

from app.services.video_editor import SQUARE_PIXELS, fit


def track_points(settings, asset_row, track_id):
    from app.v2.media_assets import read_manifest
    if track_id is None:
        return []
    tracks = read_manifest(settings, asset_row)["tracks"]
    return next((track["points"] for track in tracks if track["id"] == track_id), [])


def _usable(points, start, end):
    if not (isfinite(start) and isfinite(end) and end > start):
        return []
    clean = []
    for point in points:
        t, box = point["time"], point["box"]
        values = [box[field] for field in ("x", "y", "width", "height")]
        if not all(isinstance(value, (int, float)) and isfinite(value) for value in [t, *values]):
            return []
        x, y, w, h = values
        if min(x,y) < 0 or min(w,h) <= 0 or max(x+w,y+h) > 1.00001:
            return []
        if start - 2 <= t <= end + 2:
            if clean and t <= clean[-1][0]:
                return []
            clean.append((t,x,y,w,h))
    return clean


def _spans(samples):
    groups = []
    for sample in samples:
        if not groups or sample[0] - groups[-1][-1][0] > 3.25:
            groups.append([])
        groups[-1].append(sample)
    return [g for g in groups if len(g) >= 3]


def _crop(samples, width, height, start):
    if min(width,height) < 4 or width/height <= 9/16:
        return None
    crop_height = height // 2 * 2
    crop_width = min(width//2*2, round(crop_height*9/16/2)*2)
    if crop_width < 2:
        return None
    # Deadband small changes, then bound command length on long, high-sampling clips.
    positions = []
    previous = None
    for t,x,_,w,_ in samples:
        pos = min(width-crop_width,max(0.,(x+w/2)*width-crop_width/2))
        if previous is not None and abs(pos-previous) < crop_width * 0.03:
            pos = previous
        positions.append((t-start,pos))
        previous = pos
    if len(positions)>24:
        positions = [positions[round(i*(len(positions)-1)/23)] for i in range(24)]
    # An expression can be compact while still cutting off a face between two retained points.
    # Check every detection against the interpolated window with a small breathing margin.
    j = 0
    for timestamp,x,_,w,_ in samples:
        t = timestamp-start
        while j+1<len(positions)-1 and positions[j+1][0]<t:
            j+=1
        ta,a = positions[j]
        tb,b = positions[min(j+1,len(positions)-1)]
        weight = min(1.,max(0.,(t-ta)/(tb-ta))) if tb>ta else 0.
        left = a+(b-a)*weight
        margin = .08*w*width
        if left > max(0.,x*width-margin)+1 or left+crop_width < min(width,(x+w)*width+margin)-1:
            return None
    expr = f"{positions[0][1]:.4f}"
    for (ta,a),(tb,b) in zip(positions,positions[1:]):
        if abs(b-a) >= .1:
            expr += f"+({b-a:.4f})*clip((t-({ta:.4f}))/{tb-ta:.4f},0,1)"
    return f"crop={crop_width}:{crop_height}:x='{expr}':y=0:exact=1"


def build_track_filter(points, media_width, media_height, edit_start, edit_end):
    """Return a crop driven by t=0 at edit_start, or None when coverage or framing is insufficient."""
    groups = _spans(_usable(points, edit_start, edit_end))
    for group in groups:
        if group[0][0] <= edit_start+1.6 and group[-1][0] >= edit_end-1.6:
            return _crop(group,media_width,media_height,edit_start)
    return None


def build_dynamic_filter(points, media_width, media_height, edit_start, edit_end, width, height):
    samples = _usable(points,edit_start,edit_end)
    groups = sorted(_spans(samples),key=lambda g:g[-1][0]-g[0][0],reverse=True)
    for group in groups:
        a = max(0.,group[0][0] - edit_start)
        b = min(edit_end-edit_start,group[-1][0]-edit_start)
        if b-a < 2.5:
            continue
        crop = _crop(group,media_width,media_height,edit_start)
        if crop:
            fade = min(.35,(b-a)/4)
            return (f"[trackin]split=2[context][person];[context]{SQUARE_PIXELS},{fit(width,height)}[wide];"
                    f"[person]{crop},{SQUARE_PIXELS},{fit(width,height)},format=yuva420p,"
                    f"fade=t=in:st={a:.4f}:d={fade:.4f}:alpha=1,"
                    f"fade=t=out:st={b-fade:.4f}:d={fade:.4f}:alpha=1[close];"
                    f"[wide][close]overlay=enable='between(t,{a:.4f},{b:.4f})'[trackout]")
    return None


def recommendation(tracks, sample_count, content_type, width, height, duration):
    plausible = [t for t in tracks if len(t["points"])>=3]
    plausible.sort(key=lambda t: -len(t["points"]))
    fallback = {"layout":"fit", "track_id":None, "reason":"Keep the whole frame. Sampled face coverage is insufficient."}
    if not plausible or sample_count < 3:
        return fallback
    if len(plausible)>1 and len(plausible[1]["points"]) >= .7*len(plausible[0]["points"]):
        return {"layout":"fit", "track_id":None, "reason":"Multiple sustained tracks share the frame. Select a primary subject manually."}
    track = plausible[0]
    points = track["points"]
    if len(points)/sample_count < .5:
        return fallback
    xs = [p["box"]["x"]+p["box"]["width"]/2 for p in points]
    ys = [p["box"]["y"]+p["box"]["height"]/2 for p in points]
    if (content_type in ("gaming","livestream") and (median(xs) < .3 or median(xs) > .7)
            and (median(ys)<.35 or median(ys)>.65) and max(xs)-min(xs)<.1 and max(ys)-min(ys)<.1):
        return {"layout":"split", "track_id":track["id"], "reason":"A stable corner track is visible. Confirm its facecam region before splitting."}
    if build_track_filter(points,width,height,0,duration):
        return {"layout":"track", "track_id":track["id"], "reason":"The primary sampled track fits a continuous portrait crop."}
    if build_dynamic_filter(points,width,height,0,duration,360,640):
        return {"layout":"dynamic", "track_id":track["id"], "reason":"Use the full frame around gaps in tracking coverage."}
    return fallback
