const fs=require('fs'),path=require('path'),o=[];
const c={bg:'#f5f8fc',ink:'#172b40',muted:'#526678',panel:'#fff',edge:'#b9c8d8',navy:'#203447',blue:'#2563a5',green:'#07816d',orange:'#c56c00',purple:'#8055a6',red:'#d23939',gnd:'#263442',soft:'#e5edf7'};
const esc=s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
function t(x,y,s,z=17,f=c.ink,a='start',w=400){o.push(`<text x="${x}" y="${y}" font-size="${z}" fill="${f}" text-anchor="${a}" font-weight="${w}">${esc(s)}</text>`)}
function r(x,y,w,h,f=c.panel,s=c.edge,rx=9,d=''){o.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" fill="${f}" stroke="${s}" stroke-width="2"${d?` stroke-dasharray="${d}"`:''}/>`)}
function ln(x1,y1,x2,y2,s=c.ink,w=3){o.push(`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${s}" stroke-width="${w}" stroke-linecap="round"/>`)}
function head(x,y,w,s){r(x,y,w,48,c.navy,c.navy,7);t(x+16,y+31,s,21,'#fff','start',500)}
function row(x,y,w,left,right,color=c.ink){r(x,y,w,31,'#fff','#d6e0e9',5);t(x+10,y+21,left,14,c.muted,'start',500);t(x+w-10,y+21,right,14,color,'end',500)}
function motor(x,y,name,a,b,color){t(x,y-10,name,17,c.ink,'start',500);r(x,y,110,66,'#b8b8ac','#74796f',5);r(x+110,y+9,38,48,'#d1a83d','#8e712c',2);ln(x+23,y+66,x+23,y+88,color,4);ln(x+82,y+66,x+82,y+88,color,4);t(x+23,y+108,a,13,color,'middle',500);t(x+82,y+108,b,13,color,'middle',500)}
function dip(x,y,title,left,right){
  t(x+150,y+21,title,17,c.ink,'middle',500);r(x+118,y+42,64,338,'#30383e','#141e25',5);
  o.push(`<path d="M${x+136} ${y+42} A14 14 0 0 0 ${x+164} ${y+42}" fill="${c.panel}"/>`);
  o.push(`<text x="${x+156}" y="${y+230}" transform="rotate(-90 ${x+156} ${y+230})" font-size="19" fill="#fff" text-anchor="middle" font-weight="500">L293D</text>`);
  left.forEach((v,i)=>{const yy=y+69+i*40;r(x+108,yy-8,10,8,'#d5bd72','#9b8548',0);t(x+130,yy,v[0],13,'#fff','start',500);t(x+100,yy,v[1],13,v[2],'end',500)});
  right.forEach((v,i)=>{const yy=y+69+i*40;r(x+182,yy-8,10,8,'#d5bd72','#9b8548',0);t(x+170,yy,v[0],13,'#fff','end',500);t(x+200,yy,v[1],13,v[2],'start',500)});
}
o.push(`<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1580" viewBox="0 0 2000 1580" role="img" aria-labelledby="title desc"><title id="title">PitDivers final four-motor wiring</title><desc id="desc">Final FNK0082 GPIO and wiring plan for camera, SD, three sensors, a 74HC595, two L293D drivers and four motors.</desc><style>text{font-family:Arial,Helvetica,sans-serif}</style>`);
r(0,0,2000,1580,c.bg,c.bg,0);t(40,52,'PITDIVERS / FINAL COMPLETE WIRING',30,c.ink,'start',500);t(40,84,'FNK0082 • camera + SD • DHT11 + HC-SR04 + MPU6050 • 74HC595 • 2 × L293D • 4 motors',19,c.muted);r(40,103,1920,43,c.soft,c.soft,6);t(56,131,'Direction uses the 74HC595. GPIO19 controls both left enables; GPIO20 controls both right enables. All GND connections join.',17);

// ESP32 GPIO allocation
head(40,175,440,'1  ESP32-S3 GPIO allocation');r(40,233,440,900,'#202c35','#101a21',11);r(145,258,230,105,'#b9c2c8','#77818a',4);t(260,306,'ESP32-S3',23,c.ink,'middle',500);t(260,338,'WROOM N16R8',17,c.ink,'middle');r(162,386,196,58,'#ae803c','#705523',3);r(205,396,110,37,'#17212b','#17212b',3);t(260,470,'Onboard camera connector',15,'#fff','middle');
t(63,514,'MOTOR CONTROL',15,'#b9cee3','start',500);[['GPIO1','74HC595 DATA',c.purple],['GPIO2','74HC595 CLOCK',c.purple],['GPIO48','74HC595 LATCH',c.purple],['GPIO19','LEFT PWM × 2',c.blue],['GPIO20','RIGHT PWM × 2',c.green]].forEach((v,i)=>{t(65,548+i*35,v[0],15,'#fff','start',500);t(176,548+i*35,v[1],15,v[2])});
t(63,752,'SENSORS',15,'#b9cee3','start',500);[['GPIO21','DHT11 DATA',c.orange],['GPIO47','SONAR TRIG',c.orange],['GPIO14','SONAR ECHO',c.orange],['GPIO41','I2C SDA',c.blue],['GPIO42','I2C SCL',c.green]].forEach((v,i)=>{t(65,786+i*35,v[0],15,'#fff','start',500);t(176,786+i*35,v[1],15,v[2])});
t(63,989,'FIXED / RESERVED',15,'#b9cee3','start',500);t(65,1022,'Camera: GPIO4–13, 15–18',15,'#fff');t(65,1051,'SD: CMD38 • CLK39 • DATA0 40',15,'#fff');t(65,1080,'Keep GPIO43/44 free for USB-UART',15,'#fff');t(65,1109,'Never use GPIO35/36/37: PSRAM',15,'#ffb6b6');

// 74HC595 shown as a top-view DIP-16 package with every physical pin.
head(510,175,700,'2  74HC595 direction controller / top view');r(510,233,700,310,c.panel,c.edge,11);
r(810,258,90,248,'#30383e','#141e25',5);o.push(`<path d="M${833} 258 A22 22 0 0 0 ${877} 258" fill="${c.panel}"/>`);o.push('<text x="861" y="390" transform="rotate(-90 861 390)" font-size="20" fill="#fff" text-anchor="middle" font-weight="500">74HC595</text>');
const srPinLeft=[['1','Q1 → front-left IN2',c.purple],['2','Q2 → front-right IN3',c.purple],['3','Q3 → front-right IN4',c.purple],['4','Q4 → rear-left IN1',c.green],['5','Q5 → rear-left IN2',c.green],['6','Q6 → rear-right IN3',c.green],['7','Q7 → rear-right IN4',c.green],['8','GND → common GND',c.gnd]];
const srPinRight=[['16','VCC → +3V3',c.red],['15','Q0 → front-left IN1',c.purple],['14','SER/DATA ← GPIO1',c.purple],['13','/OE → GND',c.gnd],['12','LATCH ← GPIO48',c.purple],['11','CLOCK ← GPIO2',c.purple],['10','/MR → +3V3',c.red],['9','Q7S → unused',c.muted]];
srPinLeft.forEach((v,i)=>{const yy=282+i*30;r(800,yy-8,10,8,'#d5bd72','#9b8548',0);t(822,yy,v[0],13,'#fff','start',500);t(790,yy,v[1],13,v[2],'end',500)});
srPinRight.forEach((v,i)=>{const yy=282+i*30;r(900,yy-8,10,8,'#d5bd72','#9b8548',0);t(888,yy,v[0],13,'#fff','end',500);t(920,yy,v[1],13,v[2],'start',500)});
t(535,526,'Pin 1 is upper left beside the notch; pin 16 is upper right.',14,c.muted);

// Drivers shown exactly as top-view DIP-16 packages: notch up, counter-clockwise numbering.
head(510,572,700,'3  Two L293D drivers / top view');r(510,630,700,503,c.panel,c.edge,11);
const frontL=[['1','GPIO19 · EN1',c.blue],['2','Q0 · IN1',c.purple],['3','FL+ · OUT1',c.orange],['4','GND',c.gnd],['5','GND',c.gnd],['6','FL− · OUT2',c.orange],['7','Q1 · IN2',c.purple],['8','VMOTOR+ · VCC2',c.red]];
const frontR=[['16','+5V · VCC1',c.red],['15','Q3 · IN4',c.purple],['14','FR− · OUT4',c.green],['13','GND',c.gnd],['12','GND',c.gnd],['11','FR+ · OUT3',c.green],['10','Q2 · IN3',c.purple],['9','GPIO20 · EN2',c.green]];
const rearL=frontL.map(v=>[v[0],v[1].replace('Q0','Q4').replace('Q1','Q5').replace('FL','RL'),v[2]]);
const rearR=frontR.map(v=>[v[0],v[1].replace('Q2','Q6').replace('Q3','Q7').replace('FR','RR'),v[2]]);
dip(530,662,'L293D #1 / FRONT',frontL,frontR);dip(865,662,'L293D #2 / REAR',rearL,rearR);
t(535,1081,'Pin 1 is beside the notch at upper left. Count down to pin 8,',14,c.muted);t(535,1105,'then continue at pin 9 on lower right and count upward to pin 16.',14,c.muted);

// Sensors
head(1240,175,720,'4  Sensors + onboard devices');r(1240,233,720,900,c.panel,c.edge,11);
r(1265,264,125,86,'#187ab7','#125377',7);t(1415,282,'DHT11',19,c.ink,'start',500);t(1415,311,'VCC→3V3   DATA→GPIO21   GND→GND',15,c.orange);t(1415,340,'Bare DHT11: 10 kΩ DATA→3V3 pull-up',14,c.muted);
r(1265,390,190,90,'#246e7b','#12434d',5);o.push('<circle cx="1312" cy="435" r="31" fill="#b5bcc0"/><circle cx="1312" cy="435" r="23" fill="#3f494f"/><circle cx="1407" cy="435" r="31" fill="#b5bcc0"/><circle cx="1407" cy="435" r="23" fill="#3f494f"/>');t(1480,409,'HC-SR04',19,c.ink,'start',500);t(1480,438,'VCC→5V   TRIG→GPIO47   GND→GND',15,c.orange);t(1480,467,'ECHO must pass through divider below',14,c.muted);
t(1265,520,'ECHO',15,c.orange,'start',500);ln(1320,515,1380,515,c.orange);r(1380,507,68,16,'#eddfb0','#8b7846',1);t(1414,496,'1 kΩ',13,c.ink,'middle');ln(1448,515,1530,515,c.orange);o.push(`<circle cx="1495" cy="515" r="5" fill="${c.orange}"/>`);t(1545,520,'GPIO14',15,c.orange,'start',500);ln(1495,520,1495,572,c.gnd);r(1487,572,16,50,'#eddfb0','#8b7846',1);t(1517,603,'2 kΩ',13);ln(1495,622,1495,648,c.gnd);t(1495,670,'GND',14,c.gnd,'middle',500);
r(1265,710,150,105,'#236f79','#12434d',5);r(1315,735,52,38,'#252b33','#252b33',3);t(1445,733,'MPU6050',19,c.ink,'start',500);t(1445,762,'VCC→5V*   SDA→GPIO41   SCL→GPIO42',15);t(1445,791,'GND→GND   AD0→GND (address 0x68)',15);t(1265,842,'*5V only for the Freenove 5V-rated breakout.',14,c.muted);t(1265,870,'SDA/SCL pull-ups must go to 3.3V.',14,c.muted);
r(1265,915,665,175,c.soft,c.edge,8);t(1285,946,'ONBOARD CAMERA',17,c.ink,'start',500);t(1285,975,'SIOD4 • SIOC5 • VSYNC6 • HREF7 • PCLK13 • XCLK15',14);t(1285,1002,'Y2–Y9: 11, 9, 8, 10, 12, 18, 17, 16',14);t(1285,1040,'ONBOARD SD',17,c.ink,'start',500);t(1285,1069,'CMD38 • CLK39 • DATA0 40 — no external jumpers',14);

// Motors and power
head(40,1165,1170,'5  Four motor outputs');r(40,1223,1170,195,'#e1efeb',c.edge,10);motor(80,1260,'Front left','FL+','FL−',c.orange);motor(345,1260,'Front right','FR+','FR−',c.green);motor(610,1260,'Rear left','RL+','RL−',c.orange);motor(875,1260,'Rear right','RR+','RR−',c.green);t(80,1398,'Swap both leads of any motor that spins in the wrong physical direction.',14,c.muted);
head(1240,1165,720,'6  Power + protection');r(1240,1223,720,304,c.panel,c.edge,11);t(1265,1255,'4 × AA ≈ 6 V → switch → both L293D pin 8',16,c.red,'start',500);t(1265,1285,'USB-UART powers ESP32; ESP32 5V → both pin 16',16);t(1265,1315,'Common GND joins battery negative, ESP32, sensors and all ICs',16,c.gnd);t(1265,1355,'• 10 kΩ: GPIO19→GND and GPIO20→GND',15);t(1265,1383,'• Per L293D: 100 nF on pin 16 and pin 8 to GND',15);t(1265,1411,'• 100 µF across VMOTOR+ / GND near the drivers',15);t(1265,1439,'• 100 nF directly across each motor',15);t(1265,1474,'Build the final circuit on the general/perfboard ground bus.',14,c.muted);
t(40,1438,'FINAL GPIO SUMMARY',18,c.ink,'start',500);t(40,1470,'Motor bus: 1 DATA • 2 CLOCK • 48 LATCH • 19 LEFT PWM • 20 RIGHT PWM',16);t(40,1499,'Sensors: 21 DHT • 47 TRIG • 14 ECHO • 41 SDA • 42 SCL',16);t(40,1528,'Do not join driver outputs. GPIO2/48 may flash onboard LEDs while shifting; disable unrelated LED code.',15,c.orange);t(40,1560,'L293D numbers are physical DIP-16 pins, viewed from above with the notch upward.',14,c.muted);
o.push('</svg>');fs.writeFileSync(path.join(__dirname,'pitdivers-complete-wiring.svg'),o.join('\n'));
