# ACEScc / ACEScct as OCIO/CLF (LogCamera, no 1D LUT)

## ACEScc inverse CLF + bake remap

`get_acescc_clf_ops()` uses **LogCameraTransform** (CLF **cameraLinToLog** / **cameraLogToLin**), not LogAffine and not BuiltIn `ACEScc_to_ACES2065-1` (which can use internal LUTs). Same piecewise model as SMPTE ACEScc:

- Linear segment for AP1 linear `x < 2^-15`
- Log segment `(log2(x)+9.72)/17.52` above the break

Then **Range** maps ACEScc code \([-0.3584, 0.78]\) ↔ `[0,1]` for the 3D LUT domain.

## ACEScct forward + inverse CLF

`get_acescct_encode_ops()` / `get_acescct_decode_ops()` use explicit **LogCamera** + fixed AP0↔AP1 matrices matching OCIO BuiltIn `ACEScct_to_ACES2065-1` (break `1/128`, log slope/offset as in that BuiltIn). CLF forward shows **cameraLinToLog**; inverse **cameraLogToLin**.

## CLF example (ACEScc encode)

```xml
<Log inBitDepth="32f" outBitDepth="32f" style="cameraLinToLog">
  <LogParams base="2"
    linSideSlope="1" linSideOffset="0"
    logSideSlope="0.0570776255707763" logSideOffset="0.554794520547945"
    linSideBreak="0.000030517578125" />
</Log>
```

`linSideBreak = 2^-15`.

## Summary

| Role        | OCIO              | CLF              |
|------------|-------------------|------------------|
| ACEScc inv | LogCameraTransform| cameraLinToLog / cameraLogToLin |
| ACEScct fwd/inv | LogCameraTransform | cameraLinToLog / cameraLogToLin |

`get_acescc_full_clf_ops()` is an alias of `get_acescc_clf_ops()`.
