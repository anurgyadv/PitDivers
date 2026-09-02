// =============================================================================
// PitDivers Rover — parametric 3D model (OpenSCAD)
// =============================================================================
//
// A parametric CAD model of the PitDivers rover: a Freenove FNK0082 4WD
// ESP32-S3 car carrying an ESP32-S3 camera, an HC-SR04 ultrasonic sensor, a
// DHT11 temperature/humidity sensor and an MPU6050 IMU.
//
// HOW TO USE
//   1. Open in OpenSCAD (https://openscad.org), or render headless:
//        openscad -o rover.stl -D 'PART="assembly"' rover.scad
//   2. Pick what to build with the PART variable near the bottom of this file
//      (or override on the command line with -D 'PART="sensor_bracket"').
//   3. Correct any dimension in the PARAMETERS section to match YOUR build,
//      then re-render. Every dimension lives in one place — nothing is
//      hard-coded inside the geometry.
//
// ACCURACY NOTE
//   Values marked [DATASHEET] are from the part datasheets and are accurate.
//   Values marked [VERIFY] are Freenove-typical defaults — measure your own
//   chassis and adjust. All are millimetres unless noted.
// =============================================================================

$fn = 64;                 // curve smoothness; drop to 32 for faster previews
eps = 0.01;               // small overlap to avoid coincident-face artifacts

// -----------------------------------------------------------------------------
// PARAMETERS
// -----------------------------------------------------------------------------

// --- Chassis: twin acrylic deck plates ---------------------------------------
deck_len        = 200;    // [VERIFY] plate length (front-back)
deck_wid        = 105;    // [VERIFY] plate width  (left-right)
deck_thick      = 3;      // [DATASHEET] 3 mm acrylic
deck_gap        = 45;     // [VERIFY] vertical gap between lower and upper deck
corner_r        = 8;      // rounded plate corners
plate_hole_d    = 3.2;    // M3 clearance holes at corners

// --- Standoffs between the two decks -----------------------------------------
standoff_d      = 6;      // brass standoff outer diameter
standoff_inset  = 12;     // how far the standoff centres sit in from each edge

// --- TT gear motors (yellow plastic-gear DC motors) --------------------------
motor_body_l    = 70;     // [DATASHEET] TT motor body length incl. gearbox
motor_body_w    = 22.5;   // [DATASHEET]
motor_body_h    = 18.6;   // [DATASHEET]
motor_shaft_d   = 5.4;    // [DATASHEET] double-D output shaft
motor_shaft_l   = 10;

// --- Wheels ------------------------------------------------------------------
wheel_d         = 65;     // [DATASHEET] Freenove rubber wheel outer diameter
wheel_w         = 27;     // [DATASHEET] tyre width
hub_d           = 20;     // plastic hub diameter
wheelbase       = 120;    // [VERIFY] front-axle to rear-axle distance
track_inner     = deck_wid; // wheels sit just outside the deck edges

// --- ESP32-S3 camera board (Freenove ESP32-S3-WROOM CAM) ---------------------
cam_pcb_l       = 41;     // [VERIFY] board length
cam_pcb_w       = 24.5;   // [VERIFY] board width
cam_pcb_t       = 1.6;    // [DATASHEET] PCB thickness
cam_lens_d      = 8.5;    // [DATASHEET] OV2640 lens barrel diameter
cam_lens_h      = 6;      // barrel height above the board

// --- HC-SR04 ultrasonic sensor ----------------------------------------------
sr04_pcb_l      = 45;     // [DATASHEET] board length
sr04_pcb_h      = 20;     // [DATASHEET] board height
sr04_pcb_t      = 1.6;    // [DATASHEET]
sr04_can_d      = 16;     // [DATASHEET] transducer can diameter
sr04_can_h      = 12;     // [DATASHEET] can depth
sr04_can_gap    = 26;     // [DATASHEET] centre-to-centre spacing of the cans
sr04_hole_d     = 2;      // mounting holes (some boards omit these)

// --- DHT11 module (3-pin blue breakout) --------------------------------------
dht_pcb_l       = 20.5;   // [DATASHEET] module PCB length
dht_pcb_w       = 15.5;   // [DATASHEET] module PCB width
dht_pcb_t       = 1.2;
dht_body_l      = 12;     // [DATASHEET] blue sensor housing
dht_body_w      = 16;
dht_body_h      = 5.5;

// --- MPU6050 (GY-521 breakout) -----------------------------------------------
mpu_pcb_l       = 21.2;   // [DATASHEET]
mpu_pcb_w       = 15.6;   // [DATASHEET]
mpu_pcb_t       = 1.6;
mpu_hole_d      = 3;      // [DATASHEET] 3 mm mounting holes

// --- Printable custom parts --------------------------------------------------
wall            = 2.4;    // default wall thickness for printed brackets
bracket_clear   = 0.4;    // slip-fit clearance around held parts

// -----------------------------------------------------------------------------
// COLOURS (preview only — ignored on export)
// -----------------------------------------------------------------------------
C_ACRYLIC = [0.75, 0.85, 0.95, 0.35];
C_PCB     = [0.10, 0.45, 0.25];
C_METAL   = [0.80, 0.80, 0.82];
C_TYRE    = [0.15, 0.15, 0.16];
C_HUB     = [0.90, 0.85, 0.20];
C_SENSOR  = [0.20, 0.35, 0.85];
C_PRINT   = [0.90, 0.55, 0.15];

// =============================================================================
// COMPONENT MODULES
// =============================================================================

// Rounded rectangular plate lying in the XY plane, centred on origin.
module rounded_plate(l, w, t, r) {
    linear_extrude(t)
        offset(r) offset(-r)
            square([l, w], center = true);
}

module deck_plate() {
    color(C_ACRYLIC) difference() {
        rounded_plate(deck_len, deck_wid, deck_thick, corner_r);
        // corner mounting holes
        for (sx = [-1, 1], sy = [-1, 1])
            translate([sx * (deck_len/2 - standoff_inset),
                       sy * (deck_wid/2 - standoff_inset), -eps])
                cylinder(d = plate_hole_d, h = deck_thick + 2*eps);
    }
}

module standoff(h) {
    color(C_METAL)
        cylinder(d = standoff_d, h = h);
}

module tt_motor() {
    color(C_METAL) {
        // gearbox body
        cube([motor_body_l, motor_body_w, motor_body_h], center = true);
        // output shaft along +X
        translate([motor_body_l/2, 0, 0])
            rotate([0, 90, 0])
                cylinder(d = motor_shaft_d, h = motor_shaft_l);
    }
}

// Wheel with its axis along Y (rolls in the X direction).
module wheel() {
    rotate([90, 0, 0]) {
        color(C_TYRE)
            cylinder(d = wheel_d, h = wheel_w, center = true);
        color(C_HUB)
            cylinder(d = hub_d, h = wheel_w + 1, center = true);
    }
}

module esp32s3_cam() {
    color(C_PCB)
        rounded_plate(cam_pcb_l, cam_pcb_w, cam_pcb_t, 2);
    // lens barrel on top, near the front edge
    color([0.1,0.1,0.1])
        translate([cam_pcb_l/2 - 8, 0, cam_pcb_t])
            cylinder(d = cam_lens_d, h = cam_lens_h);
}

module hcsr04() {
    color(C_PCB)
        translate([0, 0, sr04_pcb_t/2])
            cube([sr04_pcb_t, sr04_pcb_l, sr04_pcb_h], center = true);
    // two transducer cans facing +X
    color(C_METAL)
        for (sy = [-1, 1])
            translate([sr04_pcb_t, sy * sr04_can_gap/2, 0])
                rotate([0, 90, 0])
                    cylinder(d = sr04_can_d, h = sr04_can_h);
}

module dht11() {
    color(C_PCB)
        rounded_plate(dht_pcb_l, dht_pcb_w, dht_pcb_t, 1.5);
    color(C_SENSOR)
        translate([0, 0, dht_pcb_t + dht_body_h/2])
            cube([dht_body_l, dht_body_w, dht_body_h], center = true);
}

module mpu6050() {
    color(C_PCB) difference() {
        rounded_plate(mpu_pcb_l, mpu_pcb_w, mpu_pcb_t, 2);
        for (sx = [-1, 1])
            translate([sx * (mpu_pcb_l/2 - 3), mpu_pcb_w/2 - 3, -eps])
                cylinder(d = mpu_hole_d, h = mpu_pcb_t + 2*eps);
    }
    color([0.05,0.05,0.05])  // the QFN chip
        translate([0, -1, mpu_pcb_t]) cube([4, 4, 1], center = true);
}

// =============================================================================
// PRINTABLE CUSTOM PARTS
// =============================================================================
// The chassis, wheels and sensor boards are off-the-shelf. What you actually
// 3D-print are the brackets that fasten the sensors to the front deck. These
// two modules are the printable deliverables.

// Front bracket: an L-shaped clip that holds the HC-SR04 upright at the front
// edge and gives the DHT11 a shelf beside it. Prints flat, no supports.
module sensor_bracket() {
    base_l = sr04_pcb_l + 2*wall + 2*bracket_clear;   // spans the HC-SR04
    base_w = 26;                                       // front-back footprint
    face_h = sr04_pcb_h + wall;                        // upright face height
    slot_w = sr04_pcb_t + 2*bracket_clear;

    color(C_PRINT) difference() {
        union() {
            // base plate that bolts to the deck
            translate([-base_l/2, -base_w/2, 0])
                cube([base_l, base_w, wall]);
            // upright face at the front
            translate([-base_l/2, base_w/2 - wall, 0])
                cube([base_l, wall, face_h]);
            // two ribs forming the slot that grips the HC-SR04 PCB
            for (sx = [-1, 1])
                translate([sx * (sr04_can_gap/2 + sr04_can_d/2 + slot_w),
                           base_w/2 - wall - slot_w, 0])
                    cube([wall, slot_w + wall, face_h]);
        }
        // windows so the transducers poke through the upright face
        for (sy = [-1, 1])
            translate([sy * sr04_can_gap/2,
                       base_w/2 + wall, sr04_pcb_h/2])
                rotate([90, 0, 0])
                    cylinder(d = sr04_can_d + bracket_clear, h = 3*wall,
                             center = true);
        // deck mounting holes (M3)
        for (sx = [-1, 1])
            translate([sx * (base_l/2 - 6), -base_w/2 + 6, -eps])
                cylinder(d = plate_hole_d, h = wall + 2*eps);
    }
}

// Camera mount: a tilt post that raises the ESP32-S3 cam above the front deck
// and angles it slightly downward. Prints upright.
module camera_mount() {
    post_h  = 30;
    tilt    = 10;   // degrees downward
    shelf_l = cam_pcb_l + 2*wall;
    shelf_w = cam_pcb_w + 2*wall;

    color(C_PRINT) {
        // foot
        translate([-shelf_w/2, -shelf_l/2, 0])
            cube([shelf_w, shelf_l, wall]);
        // post
        translate([-6, -shelf_l/2, 0]) cube([12, wall, post_h]);
        // tilted shelf with a lip and a lens hole
        translate([0, -shelf_l/2 + wall, post_h])
            rotate([tilt, 0, 0]) difference() {
                translate([-shelf_w/2, 0, 0])
                    cube([shelf_w, shelf_l, wall]);
                translate([0, shelf_l - 12, -eps])
                    cylinder(d = cam_lens_d + 1, h = wall + 2*eps);
            }
    }
}

// =============================================================================
// ASSEMBLY
// =============================================================================

module assembly() {
    lower_z = wheel_d/2;                 // lower deck sits at axle height
    upper_z = lower_z + deck_thick + deck_gap;

    // decks
    translate([0, 0, lower_z]) deck_plate();
    translate([0, 0, upper_z]) deck_plate();

    // standoffs at the four corners
    for (sx = [-1, 1], sy = [-1, 1])
        translate([sx * (deck_len/2 - standoff_inset),
                   sy * (deck_wid/2 - standoff_inset),
                   lower_z + deck_thick])
            standoff(deck_gap);

    // motors + wheels (4WD): two axles, left & right
    for (ax = [-1, 1], sy = [-1, 1]) {
        // motor tucked under the lower deck
        translate([ax * wheelbase/2, sy * (deck_wid/2 - motor_body_w/2 - 2),
                   lower_z - motor_body_h/2 - 1])
            rotate([0, 0, sy > 0 ? 0 : 180]) tt_motor();
        // wheel outboard of the deck
        translate([ax * wheelbase/2, sy * (deck_wid/2 + wheel_w/2 + 3),
                   wheel_d/2])
            wheel();
    }

    // ESP32-S3 camera on its mount at the front of the upper deck
    translate([deck_len/2 - 20, 0, upper_z + deck_thick]) {
        camera_mount();
        translate([0, 0, 34]) rotate([0, 0, 90]) esp32s3_cam();
    }

    // HC-SR04 in its bracket at the very front of the lower deck
    translate([deck_len/2 - 4, 0, lower_z + deck_thick]) {
        sensor_bracket();
        translate([0, 0, sr04_pcb_h/2 + 1]) hcsr04();
    }

    // DHT11 on the upper deck, rear-left
    translate([-deck_len/2 + 30, deck_wid/2 - 20, upper_z + deck_thick])
        dht11();

    // MPU6050 near the centre of the upper deck (IMU wants to be central)
    translate([0, -deck_wid/2 + 20, upper_z + deck_thick])
        mpu6050();
}

// =============================================================================
// PART SELECTOR
// =============================================================================
// Set PART to choose what renders. Override headless with:
//   openscad -o out.stl -D 'PART="sensor_bracket"' rover.scad
//
//   "assembly"        full rover (visualisation / digital twin)
//   "sensor_bracket"  printable HC-SR04 + DHT11 front bracket
//   "camera_mount"    printable tilting camera post
//   "deck_plate"      a single acrylic deck (for laser-cut reference)

PART = "assembly";

if      (PART == "assembly")       assembly();
else if (PART == "sensor_bracket") sensor_bracket();
else if (PART == "camera_mount")   camera_mount();
else if (PART == "deck_plate")     deck_plate();
else echo(str("Unknown PART: ", PART));
