from pathlib import Path

from builder.video_frames import frame_jobs


def test_jobs_name_frames_by_object_video_and_time():
    curation = {"frame_sources": {"487620": [{"video": "20261016_101903.mp4", "t": [2.0, 3.5]}]},
                "calibration_sources": {"487620": [{"video": "20261016_101903.mp4", "t": [9.0]}], "none": [{"video": "v.mp4", "t": [1.0]}]}}
    jobs = frame_jobs(curation, Path("/videos"), Path("/pack"))
    outs = [str(j[2].as_posix()) for j in jobs]
    assert outs == ["/pack/frames/487620_101903_020.jpg", "/pack/frames/487620_101903_035.jpg",
                    "/pack/calibration-frames/487620_101903_090.jpg", "/pack/calibration-frames/none_v_010.jpg"]
    assert jobs[0][0] == Path("/videos/20261016_101903.mp4") and jobs[0][1] == 2.0
