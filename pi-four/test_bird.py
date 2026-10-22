import cv2
import sys
import time

if len(sys.argv) != 2:
    print("Usage: python test_bird.py image.jpg")
    sys.exit(1)

image_path = sys.argv[1]

net = cv2.dnn.readNetFromDarknet(
    "models/yolov4-tiny.cfg",
    "models/yolov4-tiny.weights"
)

net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

image = cv2.imread(image_path)

if image is None:
    print("Could not open image:", image_path)
    sys.exit(1)

start = time.time()

model = cv2.dnn_DetectionModel(net)
model.setInputParams(
    size=(416, 416),
    scale=1/255,
    swapRB=True
)

classes, scores, boxes = model.detect(
    image,
    confThreshold=0.25,
    nmsThreshold=0.4
)

elapsed = time.time() - start

with open("models/coco.names") as f:
    names = f.read().splitlines()

birds = 0

for class_id, score, box in zip(classes, scores, boxes):
    label = names[int(class_id)]

    if label != "bird":
        continue

    birds += 1
    x, y, w, h = box

    cv2.rectangle(
        image,
        (x, y),
        (x+w, y+h),
        (0, 255, 0),
        2
    )

    cv2.putText(
        image,
        f"Bird {float(score):.2f}",
        (x, max(20, y-10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 255, 0),
        2
    )

print("Birds detected:", birds)
print("Processing time:", round(elapsed, 2), "seconds")

cv2.imwrite("bird-result.jpg", image)
print("Annotated image saved as bird-result.jpg")
