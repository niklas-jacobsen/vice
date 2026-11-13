# Homebrew formula for a personal tap (e.g. niklas-jacobsen/homebrew-tap, file Formula/vice-ai.rb).
#
# After each PyPI release, set `url` to the new sdist and `sha256` to its checksum
# (printed by the Release workflow, or: curl -sL <url> | shasum -a 256).
#
# This installs from PyPI wheels into a private virtualenv. That is fine for a tap but
# would not be accepted into homebrew-core, which requires every dependency as a
# `resource` built from source; onnxruntime does not publish an sdist.
class ViceAi < Formula
  include Language::Python::Virtualenv

  desc "Zero-UI ambient memory for your notes"
  homepage "https://github.com/niklas-jacobsen/vice"
  url "https://files.pythonhosted.org/packages/source/v/vice-ai/vice_ai-0.1.0.tar.gz"
  sha256 "REPLACE_WITH_SDIST_SHA256"
  license "MIT"

  depends_on :macos
  depends_on "python@3.12"

  def install
    venv = virtualenv_create(libexec, "python3.12")
    system libexec/"bin/python", "-m", "pip", "install", "--no-cache-dir", "vice-ai[mcp]==#{version}"
    bin.install_symlink libexec/"bin/vice"
  end

  service do
    run [opt_bin/"vice", "run"]
    keep_alive crashed: true
    log_path var/"log/vice.log"
    error_log_path var/"log/vice.err.log"
  end

  def caveats
    <<~EOS
      Run `vice setup` first. Then either `vice start` or `brew services start vice-ai`
      (use one, not both).
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/vice --version")
  end
end
