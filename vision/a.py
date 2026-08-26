python .\vision\live_da3_depth.py --stream-url http://192.168.0.69:81/stream --process-res 392 --inference-fps 5 --keyframe-dir .\data\live_capture_01 --keyframe-fps 2

cd C:\Users\Anurag\Documents\ChatGPT\PitDivers
python .\vision\live_da3_map.py --stream-url http://192.168.0.69:81/stream --keyframe-dir .\data\live_map_01 --output .\runs\live_map_01\map.ply


python .\vision\live_da3_depth.py --stream-url http://192.168.0.69:81/stream --process-res 504 --inference-fps 5 --keyframe-dir .\data\live_capture_02_svga --keyframe-fps 2


da3 images ".\data\live_capture_02_svga" --model-dir depth-anything/DA3-BASE --export-format glb --export-dir ".\runs\live_capture_02_svga" 