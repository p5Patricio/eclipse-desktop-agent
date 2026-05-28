from eclipse_agent.runtime_diagnostics import CapabilityStatus, RuntimeDiagnostics


def test_runtime_diagnostics_counts_ready_capabilities():
    diagnostics = RuntimeDiagnostics(
        capabilities=(
            CapabilityStatus("a", True, "ok"),
            CapabilityStatus("b", False, "missing", "install b"),
        )
    )

    output = diagnostics.render()

    assert diagnostics.ready_count == 1
    assert "1/2 ready" in output
    assert "install b" in output
