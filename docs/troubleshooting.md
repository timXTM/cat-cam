# Troubleshooting

Most CatCam problems are easy to narrow down. Start with the live preview and the messages on the Dashboard.

## The page will not open

1. Make sure your phone or computer is on the **same home network** as CatCam.
2. Check the address. In the current installation it is `http://192.168.1.201:8080`.
3. Try another browser or reload the page.
4. If other devices also cannot open it, the camera may be off or disconnected. Check its power and network cable or Wi-Fi.
5. Wait a minute and try again. CatCam may be restarting after a camera problem.

!!! note "CatCam is local"
    The dashboard is served by the camera on your home network. It is not reachable from outside your home unless your network has been specifically configured for it. The **Help** guide is separate and works anywhere.

## The dashboard says "Camera stalled"

This message means CatCam is running, but the camera has stopped producing frames.

1. Wait up to **three minutes**. CatCam has a watchdog that restarts the camera service automatically if no frame arrives for 180 seconds.
2. Reload the page. The message should return to the live motion readout.
3. If it stays stalled after several minutes, power-cycle the camera and wait for it to start again.
4. If this happens often, check the camera ribbon cable and its connector. A loose cable can cause repeated stalls.

While the camera is stalled, motion detection and captures are paused. Events already saved are safe.

## The header says "Offline"

The header checks the CatCam status service.

- **Offline on every page** — the camera service may be down or the network may be interrupted. Reload, wait, then power-cycle if needed.
- **Offline only on one device** — that device has lost its connection to the home network.
- **Live on the Dashboard but Offline elsewhere** — reload the page. The header refreshes its status every 30 seconds.

## The live preview is frozen

- Reload the page.
- Check the motion readout. If it says **Camera stalled**, follow the steps above.
- If the readout updates but the image does not, close other browser tabs using CatCam. The camera sends a limited number of preview frames.
- Try the **⛶** fullscreen button, then exit fullscreen. This can restart the preview.
- On a slow connection, raise **Live preview interval** in [Settings](settings.md#thumbnails-live-preview) to reduce bandwidth.

## The image is sideways or upside down

Open [Settings → Camera mounting & image orientation](settings.md#camera-mounting-image-orientation).

1. Choose the mounting that matches how the camera is physically attached.
2. Check the live orientation preview on the right.
3. If it is still wrong, try the **opposite sideways** option.
4. If needed, use **Advanced: override output rotation** to set 0°, 90°, 180°, or 270°.

Changes apply to the live view and **new** captures. Photos already saved keep their original orientation.

!!! tip "Portrait versus landscape"
    The **Portrait / Wide layout** buttons on the Dashboard only change the page layout. They do not rotate the camera. Use the mounting setting for rotation.

## No motion captures are being recorded

Check these in order:

1. **Is motion enabled?** [Settings → Motion detection](settings.md#motion-detection) must have **Enable motion-triggered captures** turned on.
2. **Is the ROI over the feeder?** The dashed box on the Dashboard must cover the place where birds land.
3. **Is the threshold too high?** Lower **Motion trigger threshold** on the Dashboard. Try 10–15%.
4. **Is the pixel difference too high?** Lower **Pixel difference threshold** in Settings. The default is 20.
5. **Is the cooldown too long?** **Minimum seconds between motion bursts** defaults to 5 seconds.
6. **Is it dark?** Motion detection needs enough light to see a difference between frames.
7. **Test manually.** Press **▣ Capture 6 photos now**. If a manual burst works, the camera and storage are fine and the issue is motion sensitivity.

## Too many captures

- Shrink the ROI to the feeder only.
- Raise **Motion trigger threshold**.
- Raise **Pixel difference threshold**.
- Increase **Minimum seconds between motion bursts**.
- Increase **Motion sampling interval** slightly.

Make one change at a time and watch **Recent activity** for a day.

## Birds visit, but there are no bird events

1. **Check the result.** Open **Recent activity**. Does the burst say `no_bird`, `pending`, or `error`?
2. **Check the detection engine.** [Settings → Bird Detection Engine](settings.md#bird-detection-engine) must point to a working service.
3. **Google Vision quota.** The card shows requests used this month. The budget is 900. If it is exhausted, wait for the new month or switch to Local AI.
4. **Local AI is unreachable.** Confirm the Pi 4 is powered on, the IP address and port are correct, and the photo folder path exists on the Pi 4.
5. **The first photo is empty.** Change **First photo checked by Google Vision** to a photo number where the bird is more visible. CatCam checks that photo first, then wraps through the others.
6. **The bird is too small or blurry.** Move the camera closer, improve focus, or clean the lens.
7. **Classification is still running.** Large bursts can take a while. Check again in a few minutes.

!!! warning "Local AI errors are not retried with Google Vision"
    If Local AI fails, CatCam marks the event as an error rather than silently spending Google Vision requests. Fix the Local AI service and the next burst will use it.

## Google Vision usage is used up

The Google Vision budget is **900 requests per calendar month**. CatCam stops at the limit to control costs.

Options:

- Wait for the next calendar month.
- Switch **Detection engine** to **Local AI** if a Pi 4 detector is available.
- Reduce the number of bursts by tightening motion detection.

The usage card is visible when Google Vision is selected.

## Discord alerts are not arriving

1. **Both switches must be on.** Enable Discord in [Settings → Bird detection & notifications](settings.md#bird-detection-notifications), and make sure the Pi-side Discord option is also enabled.
2. **The webhook must be configured on the Pi.** It is not editable in the web interface.
3. **Only bird bursts are sent.** Non-bird bursts never generate an alert.
4. **Check Recent activity.** The Discord column shows whether the alert was sent, skipped, or failed.
5. **Check the Discord channel permissions.** The webhook may have been removed or the channel may have been deleted.

## The Gallery is empty

- The default filter may be **Birds only**. Change **Show** to **All bursts**.
- A date or hour filter may be too narrow. Press **Reset** or clear the filters.
- Cleanup may have removed old non-bird bursts. This is expected.
- If even a fresh manual capture is missing, check that the camera is saving photos and that the event is not still pending.

## A burst shows fewer than six photos

Cleanup removes photos from old non-bird bursts. The card shows **available photos** only. Bird bursts and manually confirmed birds are preserved.

If a recent burst is missing photos, check free space on the camera and look for a **Classification error** on the event.

## Settings will not save

- Make sure every number is inside its allowed range. The page highlights the first invalid field.
- Use a valid **IANA timezone**, such as `America/New_York`.
- For Local AI, the host must be a valid IP address and the photo folder must be an absolute path starting with `/`.
- Press **Save all settings** again after correcting the field.
- If the status shows an error, reload the page and try once more.

## The time or date is wrong

Open [Settings → Timezone](settings.md#timezone) and choose the correct IANA timezone. Daylight saving time is automatic. Existing folder names on disk are not renamed.

## Bird Activity is empty

Bird Activity only includes **bird-positive** events.

- Choose **All recorded activity** and clear the bird type and identification filters.
- If you just started using CatCam, wait for the first bird event.
- If bursts are being classified as non-bird, see the section above.

## A species is missing from the list

Open the burst in the Gallery, press **+ Add new species**, enter the common English name, and save it. Then select it and press **Confirm species**.

## The Help link does not open

The Help link opens the guide on GitHub Pages, so it needs an internet connection. The CatCam dashboard itself works without internet.

If the page does not load:

- Check your internet connection.
- Try again in a moment.
- Open the guide directly at [https://timxtm.github.io/cat-cam/](https://timxtm.github.io/cat-cam/).

## Storage is filling up

- Lower **Non-bird retention (hours)** in [Storage & cleanup](settings.md#storage-cleanup).
- Keep **Enable automatic non-bird cleanup** on.
- Reduce false triggers by shrinking the ROI and raising the motion threshold.
- Remember that bird events and confirmed birds are kept on purpose.

## When to ask for help

Contact whoever installed or maintains your CatCam if:

- The camera stays offline after a power cycle.
- The watchdog restarts the camera repeatedly.
- The SD card or storage is full even after cleanup.
- Local AI or Discord credentials need to be changed.
- You see repeated **Classification error** results.

Include the time of the problem and a screenshot of the Dashboard or the event page. That makes it much easier to diagnose.
