# Cheapest LDS02RR connection for the PitDivers ESP32-S3

The lowest priced Australian purchase identified is the Core Electronics CE09733 MOSFET module plus a 1N5819 diode, using the Freenove kit’s capacitor, resistors and wiring. The additional parts cost is **A$1.88**, or **A$8.88 and upward including advertised standard postage**. This is a budget prototype choice: the retailer explicitly supports 3.3 V control, but the circuit has not been tested with this particular LiDAR. The better documented alternative is the Adafruit 5648 motor switch at **A$14.55 and upward delivered**, reusing the kit capacitor. Neither price includes a new power supply, tools or an unverified LiDAR mating connector.[1][2][3]

Prices were checked on 9 September 2026. Delivery figures are advertised starting rates, not a quote for a specific Perth postcode. The existing sensor purchase is excluded. No purchase is necessary to inspect and prepare the kit parts.

## What the adapter actually does

The adapter supplies the sensor electronics continuously and separately switches the motor’s negative lead with a transistor. The ESP reads serial distance data and adjusts motor speed through PWM. A MOSFET is the electronic switch that lets a small GPIO signal control motor current. A diode provides a path for motor current when the switch turns off; a capacitor helps stabilise the supply.[4]

Maker’s Pet specifies 5 V power, approximately 1 A peak supply capability, 3.3 V serial output and 3.3 V motor control. Its supported setup targets approximately five revolutions per second. These are integration specifications from the adapter developer, not a publicly available Roborock sensor datasheet. The supplied seller photo is labelled LDS02RR, 5 VDC, 0.35 A; the nameplate figure does not establish startup or stall current.[5]

Consequently, the custom PCB can be replaced by wiring and a motor switch. Connecting the motor directly to an ESP pin cannot replace that switch. A fixed motor supply also removes the speed regulation expected by the integration.

## Purchase comparison

| Route | Additional parts | Delivery / total | Assessment |
|---|---:|---|---|
| Reuse Freenove ULN2003 board | A$0 if complete kit and suitable supply are available | No delivery | Worth investigating as a bench experiment; voltage loss and package heating prevent calling it a confirmed complete solution. |
| Core CE09733 plus 1N5819 | A$1.35 + A$0.53 = **A$1.88** | Standard shipping A$7+; **A$8.88+** | Cheapest identified domestic purchase. Retailer supports 3.3 V; verify switching and heating under load. [1][2] |
| Adafruit 5648 from Core | **A$7.55** | Standard shipping A$7+; **A$14.55+** | Better documented 3.3 V interface and integrated flyback protection. Stock/dispatch indications conflicted; confirm checkout availability. [3][6] |
| Tempero DRV8833 board | **A$4.95** | Shipping unconfirmed | Potential alternative, but no demonstrated delivered-price advantage and board pin labelling needs verification. [7][8] |
| Pololu DRV8833 from Core | **A$18.30** | Standard shipping A$7+; **A$25.30+** | Documented carrier, excessive cost for this task. [9] |
| Maker’s Pet adapter | Store lists **$6**, before international delivery | Australian landed total unconfirmed | Most direct mechanical solution; no evidence it is cheapest delivered to Perth. Do not interpret the store price as A$6. [5] |
| Custom PCB or discrete surface-mount build | Depends on order minimum, assembly and connector | Unconfirmed | Unit transistor price understates one-off cost. Useful only if fabrication and soldering supplies are already available. |

These totals reuse a suitable kit capacitor. If no usable capacitor is present, add its actual price and availability. Reusing a regulated supply is conditional on its output rating and measured performance. Core’s selected-item letter service starts lower than parcel postage, but eligibility for these complete orders was not established; the comparison does not assume it.

## What can be reused from the Freenove Ultimate Starter Kit

This assessment uses **FNK0082**, matching the board recorded in the project GPIO map. Kit revisions and the contents remaining in the user’s box may differ.

| Kit item | Use in this project | Decision |
|---|---|---|
| 10 µF electrolytic capacitor | Across LiDAR 5 V and ground | Reuse if undamaged and rated at least 10 V. Observe polarity. Freenove lists it in the audio project. [10] |
| 1 kΩ and 10 kΩ resistors | Optional UART series resistance, control pulldown and prototype work | Reuse; no need for a resistor assortment purchase. [11] |
| Jumper wires and breadboard | Logic connections and initial assembly | Reuse. The LiDAR connector itself may still require soldered leads or a verified mating connector. |
| S8050 NPN and S8550 PNP transistors | Possible component-level switching circuits | Present, but not a demonstrated replacement for the motor MOSFET. Exact manufacturer, available base drive, startup current and heating remain unresolved. [11] |
| ULN2003 stepper-driver board | Possible low-side motor switch | Present and relevant; see below. Unplug the kit stepper before repurposing. [12] |
| L293D | Potential motor driver | Present in kit documentation, but both project drivers are allocated to four wheel motors. Reusing those channels changes the rover wiring. [13] |
| Relay and diode | On/off switching and relay-coil protection | The relay cannot perform the several-kHz speed PWM. The kit diode’s exact marking must be checked before treating it as the motor flyback diode. [14] |
| Extension board / breadboard power hardware | Power distribution | A 5 V label alone does not establish enough current or thermal capacity for LiDAR plus ESP. |

The kit therefore saves the capacitor, resistor and wiring purchases. It does not yet establish a fully verified zero-cost solution.

### The free ULN2003 possibility

The ULN2003 contains transistor switches and clamp diodes, so it is electrically relevant even though sold as a stepper driver. TI allows paralleling channels. A single output has a 500 mA rating; that is not enough evidence to accept an unknown LiDAR startup load. Paralleling outputs also does not eliminate the shared package’s thermal limit.[15]

Its Darlington switches lose substantially more voltage than a well-driven MOSFET. For illustration, a 1 V drop would leave about 4 V across a motor supplied from 5 V and dissipate 0.35 W at 0.35 A. Those are calculated examples, not measurements of this motor. Whether the spindle reaches its target speed depends on the actual motor and mechanical load.

A possible experiment would use matched parallel input/output channels, common ground, and the diode common connected to motor positive. Before specifying physical wiring, verify the exact board, available outputs, chip marking and load current. Do not connect the diode-common terminal to ground. The recommendation remains the inexpensive MOSFET route if the objective is to minimise both cost and troubleshooting.

### Why the S8050 is not an automatic free substitute

A bipolar transistor needs sustained base current, whereas a MOSFET primarily requires gate charging during switching. For example, designing around a forced gain of ten at 350 mA would require 35 mA of base current. This is an illustrative design calculation, not a claim that the LiDAR motor continuously draws the entire sensor nameplate current. It demonstrates why the kit’s buzzer circuit cannot simply be copied without checking the motor load and transistor specification.

The S8050/S8550 could help build a more involved driver or level-shifting circuit. That adds component identification, startup-state and PWM-timing work. For a A$1.35 module, this is not an obvious saving in effort or reliability.

## Resolving the cheap MOSFET recommendation

Core explicitly advertises CE09733 for 3.3–5 V logic and identifies two AOD4184 MOSFETs used for low-side switching. That supports using it as a budget candidate. It does not mean this LiDAR, wiring and firmware have been validated together.[1]

The earlier concern about 3.3 V operation should be understood as a qualification, not proof the module is incompatible. A transistor’s threshold voltage only describes the start of conduction, not its resistance at useful motor current. Similarly, specifications for AOD4184A should not be silently substituted for the exact AOD4184 device.

The Adafruit board provides a clearer complete-module specification: 3–20 V control, 3–30 V load supply, AO3406 switching and a built-in 1N4007 flyback diode. Its documented continuous-current capability exceeds the sensor’s stated nominal current.[6] It is the preferable purchase if avoiding a second round of hardware troubleshooting is worth the extra A$5.67 over the budget parts basket.

For CE09733, include the external 1N5819. For Adafruit, its integrated diode supplies the stated protection; an external Schottky can be considered for the several-kHz PWM implementation, but is not counted as mandatory in the manufacturer-based basket. The system still requires a powered test.

## Wiring architecture

The following table describes electrical functions, **not the physical left-to-right order of the connector in the seller photo**. Maker’s Pet warns of connector-orientation variants. Establish physical pin 1 and continuity on the delivered sensor before applying power.[4][5]

| LiDAR function | Maker’s Pet v0.3 schematic J1 pins | Connection |
|---|---|---|
| MOT+ | 1, 2 | Regulated +5 V |
| Ground | 3, 4 | Supply ground and ESP ground |
| MOT− | 5, 6 | Motor switch’s switched negative output |
| TX | 7, 8 | ESP UART receive input |
| VCC | 9, 10 | Continuous regulated +5 V |
| Ground | 11, 12 | Common ground |

Connect the MOSFET module’s power input according to its printed labels and documentation. Its control input receives ESP PWM. The sensor electronics ground remains continuously connected; only MOT− is switched. A 1N5819 used externally goes across the motor: **striped cathode to MOT+ / +5 V; anode to MOT−**. Put the electrolytic capacitor near the sensor supply connection, positive to +5 V and negative to ground. These are adaptations of the published low-side circuit.[4]

Use a regulated 5 V source with approximately 1 A available for the LiDAR, with additional capacity for the ESP and other loads. Keep wheel-motor surge current out of the LiDAR’s thin jumper ground path. Do not feed 9 V to the sensor because a kit tutorial uses a 9 V battery upstream of other circuitry. Avoid joining independent USB and external 5 V outputs without checking the board’s power arrangement.

Direct soldered leads can avoid buying a custom connector or PCB. This requires a soldering iron and strain relief; ordinary Dupont contacts must not be assumed to fit the black LiDAR socket. The exact mating connector was not established from the seller photo.

## ESP32-S3 and software integration

The local project already allocates the camera, SD card, wheel drivers, MPU6050, DHT11 and sonar pins. For an initial LiDAR test, temporarily remove the HC-SR04 and its echo divider, disable its firmware task, and use **GPIO14 as ESP UART RX and GPIO47 as motor PWM**. This is a proposed allocation, not a change already applied to the project.[16]

Leaving the existing echo divider attached would unnecessarily attenuate the LiDAR’s reported 3.3 V TX signal. A series resistor and a divider are different circuits. Sensor TX connects to ESP RX; the initial receive-only integration does not require a wire from ESP TX.

The Kaia.ai LDS library has an LDS02RR driver and a matching ESP32 example. It uses the Neato-style serial parser at 115200 baud and regulates speed using feedback. The example’s PWM setup is 10 kHz with 11-bit resolution. Its pin names are written from the LiDAR perspective, so review the actual UART constructor arguments rather than copying names blindly.[17][18][19]

Do not copy its example GPIO numbers into the camera rover: those pins overlap existing functions. Allocate an unused PWM channel and timer without disturbing camera clock generation or wheel PWM. Start with a standalone LiDAR test, then integrate camera and Wi-Fi after reliable packets and speed feedback are observed.

Add a motor shutdown response for persistent missing/invalid packets and failed startup. The inspected base driver does not itself provide a complete system-level lost-data shutdown. Choose and validate timeouts during testing; do not allow a stalled or disconnected scan stream to demand increasing PWM indefinitely.[18]

## First powered test and acceptance

1. Identify the delivered sensor model, connector orientation and motor connections with power disconnected. Confirm supply/ground continuity and absence of shorts.
2. Verify the regulated supply voltage and the control output’s off state before connecting the motor. Use a current-limited supply if available.
3. Confirm the serial output level is suitable for the ESP. A multimeter cannot fully characterise fast signal peaks; an oscilloscope or logic analyser is preferable when the actual variant is uncertain.
4. Start the motor under controlled PWM with current monitoring. Stop if it fails to start, the supply collapses or the driver heats rapidly.
5. Confirm checksum-valid packets and sustained operation near the intended scan speed. Motor rotation alone is insufficient evidence that the interface works.
6. Recheck supply stability and serial errors with camera/Wi-Fi active, then with the rover wheels operating.

This is the evidence required before saying the complete setup works. Public documentation supports the architecture, but it cannot establish the condition of the purchased sensor or correctness of an unassembled wiring harness.

## Purchasing decision

**Choose CE09733 + 1N5819 for the lowest identified domestic parts cost**, reusing the kit’s 10 µF capacitor and wiring, if a measured prototype is acceptable. **Choose Adafruit 5648 for the better documented module**, if spending about A$5.67 more is acceptable. Establish the existing 5 V supply and the connector attachment method before calling either basket complete.

A walk-in Perth option with both a verified suitable interface and lower complete cost was not established. The Jaycar IRF520 module is not a good direct 3.3 V replacement based solely on its logic-compatible marketing: the transistor’s low on-resistance is specified at a much higher gate voltage.[20][21] The Tempero DRV8833 remains a secondary option; TI documents the underlying device, but some seller pin descriptions are ambiguous, so they should not be copied into a wiring guide.[7][8]

The Freenove ULN2003 remains a credible zero-purchase experiment, not a guaranteed replacement. The next useful evidence is the actual kit driver marking, remaining components and existing power supply rating—not another expensive custom adapter order.

## Sources

1. [Core Electronics CE09733: price, logic range and postage](https://core-electronics.com.au/mosfet-power-switch-module.html).
2. [Core Electronics 1N5819 / COM-10926](https://core-electronics.com.au/schottky-diode.html).
3. [Core Electronics Adafruit 5648: Australian price and availability](https://core-electronics.com.au/adafruit-mosfet-driver-for-motors-solenoids-leds-etc-stemma-jst-ph-2mm.html).
4. [Maker’s Pet LDS02RR adapter v0.3 schematic](https://github.com/makerspet/store/blob/main/LDS02RR-ADPT-V030/schematic.pdf).
5. [Maker’s Pet LDS02RR adapter v0.4 specifications](https://makerspet.com/product/adapter-v0-4-for-lds02rr-lidar/).
6. [Adafruit 5648 manufacturer specifications](https://www.adafruit.com/product/5648).
7. [Tempero Systems DRV8833 board](https://temperosystems.com.au/products/drv8833-2-channel-dc-motor/).
8. [Texas Instruments DRV8833 datasheet](https://www.ti.com/lit/ds/symlink/drv8833.pdf).
9. [Core Electronics Pololu DRV8833 carrier](https://core-electronics.com.au/drv8833-dual-motor-driver-carrier.html).
10. [Freenove FNK0082 audio chapter: 10 µF capacitor and wiring](https://docs.freenove.com/projects/fnk0082/en/latest/fnk0082/codes/C/29_Play_SD_card_music.html).
11. [Freenove FNK0082 buzzer chapter: S8050/S8550 and resistors](https://docs.freenove.com/projects/fnk0082/en/latest/fnk0082/codes/C/7_Buzzer.html).
12. [Freenove FNK0082 stepper chapter: ULN2003 board](https://docs.freenove.com/projects/fnk0082/en/latest/fnk0082/codes/C/19_Stepper_Motor.html).
13. [Freenove FNK0082 motor-driver chapter: L293D](https://docs.freenove.com/projects/fnk0082/en/latest/fnk0082/codes/C/17_2_Motor_%26_Driver.html).
14. [Freenove FNK0082 relay chapter: relay and diode](https://docs.freenove.com/projects/fnk0082/en/latest/fnk0082/codes/C/17_Relay_%26_Motor.html).
15. [Texas Instruments ULN2003A datasheet](https://www.ti.com/lit/ds/symlink/uln2003a.pdf).
16. Local project record: `docs/wiring/FINAL_GPIO_MAP.md`, inspected 9 September 2026.
17. [Kaia.ai LDS02RR driver](https://github.com/kaiaai/LDS/blob/main/src/LDS_LDS02RR.cpp).
18. [Kaia.ai inherited Neato driver](https://github.com/kaiaai/LDS/blob/main/src/LDS_NEATO_XV11.cpp).
19. [Kaia.ai LDS02RR ESP32 example](https://github.com/kaiaai/LDS/blob/main/examples/all_lidars_lds02rr_esp32/all_lidars_lds02rr_esp32.ino).
20. [Jaycar XC4488 MOS driver](https://www.jaycar.com.au/duinotech-arduino-compatible-24v-5a-mos-driver-module/p/XC4488).
21. [Infineon IRF520N datasheet](https://www.infineon.com/assets/row/public/documents/24/49/infineon-irf520n-datasheet-en.pdf).
