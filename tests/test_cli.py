from picture_frame import cli


def test_run_web_starts_sync_loop_before_serving(monkeypatch):
    calls = []

    class RuntimeStub:
        def refresh_images(self):
            calls.append("refresh_images")

        def start_sync_loop(self):
            calls.append("start_sync_loop")

    runtime = RuntimeStub()
    monkeypatch.setattr(cli, "_runtime_from_args", lambda: (runtime, object()))
    monkeypatch.setattr(cli, "_serve_wsgi", lambda value: calls.append(f"serve:{value is runtime}"))

    cli.run_web()

    assert calls == ["refresh_images", "start_sync_loop", "serve:True"]
