package(
    default_visibility = ["//tensorflow_lite_support:internal"],
    licenses = ["notice"],  # Apache 2.0
)

exports_files([
    "yamnet_audio_classifier_with_metadata.tflite",
])

filegroup(
    name = "test_models",
    srcs = glob([
        "*.tflite",
    ]),
)

filegroup(
    name = "test_audio_clips",
    srcs = glob([
        "*.wav",
    ]),
)
