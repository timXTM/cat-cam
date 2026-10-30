# FAQ

### What is CatCam?

CatCam is a self-hosted wildlife camera for a bird feeder. It watches a small area of the image, records six photos when something moves, checks the photos for birds, and shows the results in a web dashboard, gallery, and activity report.

### Do I need an app or an account?

No. CatCam runs in your web browser. Open its address on your home network. There is no login, subscription, or cloud account for the dashboard.

### How many photos does CatCam take?

Every burst has **six full-resolution photographs**. This is fixed by design and cannot be changed in Settings.

### Does CatCam record video?

No. It shows a live preview, but it saves still photos. Each motion event is a six-photo burst.

### What is the ROI?

The **region of interest** is the dashed green box on the live preview. CatCam only reacts to movement inside that box. Drag the box over the feeder and resize it with the round handle to reduce false triggers.

### Why do the Portrait and Wide buttons not rotate the camera?

They only change the dashboard layout in your browser. To correct a sideways or upside-down image, use [Camera mounting & image orientation](settings.md#camera-mounting-image-orientation).

### What is the difference between an AI estimate and a confirmed species?

An **AI estimate** is a guess from Google Vision or the Local AI service. A **confirmed species** is a choice you made after looking at the photos. Confirmed species are more reliable and are protected from automatic cleanup.

### How do I confirm a species?

Open the burst from the [Gallery](gallery.md#confirm-or-correct-a-species), choose the species, and press **Confirm species**. If the species is missing, add it first.

### Why is a burst counted as one event when it has six photos?

Because the six photos belong to one visit. Counting photos would make a single bird look like six events. Bird Activity counts bursts, not photos.

### What happens to photos without a bird?

They are kept for a while, then removed by automatic cleanup. The default retention is **24 hours**. Only fully classified, non-bird bursts are eligible. Bird bursts and confirmed birds are never removed by cleanup.

### Can I delete a photo or burst myself?

There is no delete button in the web interface. Cleanup handles non-bird bursts automatically. To keep something, confirm it as a bird or turn cleanup off in Settings.

### Does viewing the Gallery or Bird Activity use Google Vision requests?

No. Both pages read stored results. Google Vision is only called when a new burst is classified. Bird Activity does not make new requests.

### What is the Google Vision monthly limit?

CatCam allows **900 Google Vision requests per calendar month**. The Settings page shows how many have been used and how many remain. The limit is fixed to control costs.

### What is Local AI?

Local AI sends new bursts to a separate Raspberry Pi 4 running YOLO bird detection, with optional AIY Birds species identification. It does not use the Google Vision quota. It must be set up and reachable on your network.

### What if Local AI is offline?

The event is marked as a **Classification error**. CatCam does not silently fall back to Google Vision, so it does not spend requests without your knowledge. Fix the Pi 4 service and the next burst will use it.

### Why does Discord only send birds?

Bird-only alerts keep the channel useful and avoid notifications for every leaf that moves. Non-bird bursts are never sent. Both the CatCam setting and the Pi-side setting must be enabled, and a webhook must be configured.

### Can I use CatCam when I am away from home?

The dashboard is designed for your home network. Unless your network has been specially configured, it is not reachable from the internet. This guide is hosted separately on GitHub Pages, so **Help** works anywhere.

### Does CatCam work at night?

Motion detection and photos need light. In darkness, the camera may not see enough detail to detect motion or identify birds. A well-lit feeder works best.

### Why do I get motion events with no bird?

Common causes are wind, leaves, rain, insects, squirrels, people, or a shadow. Shrink the ROI to the feeder, raise the motion threshold, and review a few bursts to see what is triggering them.

### Why did the camera miss a bird?

The bird may have been outside the ROI, too small, too blurry, or moving too fast. Motion detection may be disabled, the threshold may be too high, or classification may have checked an empty photo first. See [Troubleshooting](troubleshooting.md#birds-visit-but-there-are-no-bird-events).

### Why does the dashboard say "Camera stalled"?

The camera stopped producing frames while CatCam kept running. CatCam automatically restarts after 180 seconds without a frame. If the message persists, power-cycle the camera. See [Troubleshooting](troubleshooting.md#the-dashboard-says-camera-stalled).

### Why does the image look soft or blurry?

Try **Continuous autofocus**, or turn it off and adjust **Manual focus** while watching the live preview. Clean the lens and make sure the feeder is inside the camera's focus range. Also remember that thumbnails are smaller than the original photos; open a photo and use **Open original ↗** to judge sharpness.

### Can I change the six-photo burst or the Google Vision quota?

No. Those are protected settings. They keep capture records consistent, cleanup safe, and API costs predictable.

### Are my photos private?

Photos are stored on your camera. If you use **Google Vision**, images are sent to Google for classification. If you use **Local AI**, classification stays on your local network. Discord alerts send bird photos to the webhook you configured. The CatCam dashboard itself does not require a cloud service.

### Is there a user account or password?

The dashboard has no user accounts. Anyone who can reach the camera on your network can use it. Keep it on a trusted home network.

### How do I back up my photos?

Use **Open original ↗** in the photo viewer to save individual full-resolution photos. For a complete backup, ask whoever maintains the camera to copy the photo archive and database from the Pi.

### How do I update CatCam?

Updates are handled by whoever maintains the camera. The Help guide is updated separately on GitHub Pages, so it can be newer than the camera software.

### How do I open this guide later?

Use the **Help ↗** link in the CatCam header. You can also bookmark [https://timxtm.github.io/cat-cam/](https://timxtm.github.io/cat-cam/).

### Why does dark mode not follow me to another device?

The theme is stored in your browser, not on the camera. Each browser remembers its own choice.

### Why is the time different from my phone?

CatCam uses the timezone configured in [Settings](settings.md#timezone). Set it to your local IANA timezone. Daylight saving time is handled automatically.

### Can two people use CatCam at once?

Yes. The dashboard is read-mostly and can be opened on several devices. Avoid leaving many live previews open at once, because each viewer uses camera resources.
