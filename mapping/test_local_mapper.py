import math
import unittest

import numpy as np

from local_mapper import RoomMapper


def room_scan(pose, seq=1, boot=7):
    x, y, yaw = pose
    segments = [(-3,-2,4,-2),(4,-2,4,3),(4,3,-3,3),(-3,3,-3,-2),
                (-1.2,.7,-.3,.7),(-.3,.7,-.3,1.4),(-.3,1.4,-1.2,1.4),(-1.2,1.4,-1.2,.7)]
    ranges = []
    for angle in range(360):
        dx,dy = math.cos(yaw-math.radians(angle)),math.sin(yaw-math.radians(angle))
        distances = []
        for ax,ay,bx,by in segments:
            if ax==bx and abs(dx)>1e-9:
                t=(ax-x)/dx
                if t>0 and min(ay,by)-1e-8 <= y+t*dy <= max(ay,by)+1e-8:
                    distances.append(t)
            elif ay==by and abs(dy)>1e-9:
                t=(ay-y)/dy
                if t>0 and min(ax,bx)-1e-8 <= x+t*dx <= max(ax,bx)+1e-8:
                    distances.append(t)
        ranges.append(round(min(distances)*1000) if distances else 0)
    return dict(boot_id=boot,seq=seq,start_ms=seq*200,end_ms=seq*200+190,
                scan_time_ms=190,ranges_mm=ranges,temperature_c=24.0,
                humidity_percent=50.0,environment_age_ms=50)


class RoomMapperTest(unittest.TestCase):
    def test_known_room_translation_rotation_and_environment_position(self):
        mapper=RoomMapper()
        self.assertEqual(mapper.add(1,room_scan((0,0,0))),[0,0,0])
        for seq in range(2,7):
            expected=np.array([.06*(seq-1),.03*(seq-1),.025*(seq-1)])
            result=mapper.add(seq,room_scan(expected,seq))
            self.assertIsNotNone(result,mapper.reason)
            np.testing.assert_allclose(result,expected,atol=.045)
        self.assertEqual(len(mapper.environment),6)
        np.testing.assert_allclose(mapper.environment[-1][:2],expected[:2],atol=.045)
        self.assertTrue(any(v>1 for v in mapper.cells.values()))
        self.assertTrue(any(v<0 for v in mapper.cells.values()))

    def test_restart_and_missing_ranges_do_not_create_positions(self):
        mapper=RoomMapper()
        mapper.add(1,room_scan((0,0,0)))
        self.assertIsNone(mapper.add(2,room_scan((0,0,0),2,boot=8)))
        bad=room_scan((0,0,0),3)
        bad['ranges_mm']=[0]*360
        self.assertIsNone(mapper.add(3,bad))
        self.assertEqual(mapper.placed,1)
        self.assertEqual(len(mapper.path),1)

    def test_stale_environment_not_painted_on_map(self):
        mapper=RoomMapper()
        scan=room_scan((0,0,0))
        scan['environment_age_ms']=10000
        mapper.add(1,scan)
        self.assertEqual(mapper.environment,[])


if __name__=='__main__':
    unittest.main()
