"""A* between free-space stops, exact shortest visiting order for <=6 stops."""
import itertools
import math

def validate_points(points):
    if not isinstance(points,list) or not 1 <= len(points) <= 6:
        raise ValueError('Choose between one and six stops')
    for p in points:
        if (not isinstance(p,(list,tuple)) or len(p)!=2 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in p)):
            raise ValueError('Stops must have finite x/y coordinates')
    return [list(p) for p in points]

def plan_tour(grid,start,points,return_home=True,clearance=.23):
    points=validate_points(points)
    nodes=[list(start),*points]
    paths={}; costs={}
    for i,a in enumerate(nodes):
        if not grid.is_free(*a, clearance if return_home or i else .18):
            raise ValueError('Choose open floor with room for the rover, away from walls and unknown areas')
        for j in range(i):
            b=nodes[j]
            path=grid.plan_from_nearby(b,a,clearance)
            paths[j,i]=path; paths[i,j]=list(reversed(path))
            costs[j,i]=costs[i,j]=sum(math.dist(x,y) for x,y in zip(path,path[1:]))
    best=None
    for permutation in itertools.permutations(range(1,len(nodes))):
        order=(0,*permutation,*([0] if return_home else []))
        cost=sum(costs[a,b] for a,b in zip(order,order[1:]))
        if best is None or cost<best[0]:best=(cost,order)
    cost,order=best
    path=[]
    for a,b in zip(order,order[1:]):path.extend(grid.smooth(paths[a,b],clearance))
    return dict(goals=[nodes[i] for i in order[1:]],order=list(order[1:]),
                path=path,distance_m=cost,return_home=return_home)
