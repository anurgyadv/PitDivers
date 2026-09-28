// Keep the live pose and geometry in the same ROS coordinate frame.
function showsLiveMap(state, archived) {
  return !archived || (state?.backend === 'localization' && state.run_id === archived.run_id);
}
function displayedMap(state, archived) {
  return showsLiveMap(state, archived) ? state?.map : archived.map;
}
function routeDisplayPath(source, display) {
  const poses = new Map((display.path || []).map(p => [p[3], p]));
  return source.map(p => poses.get(p[3]) || p);
}
function routeClickSource(source, display, x, y) {
  const poses = routeDisplayPath(source, display);
  let best = -1, distance = Infinity;
  poses.forEach((p, i) => { const d = Math.hypot(p[0]-x, p[1]-y); if (d < distance) {best=i; distance=d;} });
  if (best < 0 || distance > .5) throw Error('Choose a point within 0.5 m of the recorded rover path');
  return {x_m:source[best][0], y_m:source[best][1]};
}
if (typeof module !== 'undefined') module.exports = {showsLiveMap, displayedMap, routeDisplayPath, routeClickSource};
