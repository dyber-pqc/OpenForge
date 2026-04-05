%global __python %{__python3}
%global python3_pkgversion 3.12

Name:           openforge-eda
Version:        0.1.0
Release:        1%{?dist}
Summary:        Cloud-native cryptographic hardware verification platform
License:        GPL-3.0-or-later
URL:            https://github.com/dyber-pqc/OpenForge
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  python3-devel >= 3.12
BuildRequires:  python3-pip
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  rust >= 1.75
BuildRequires:  cargo
BuildRequires:  nodejs >= 20
BuildRequires:  npm
BuildRequires:  gcc
BuildRequires:  gcc-c++
BuildRequires:  make
BuildRequires:  desktop-file-utils

Requires:       python3 >= 3.12
Requires:       python3-pyside6 >= 6.7
Requires:       python3-pydantic >= 2.0
Requires:       python3-pyyaml >= 6.0
Requires:       python3-jinja2 >= 3.1
Requires:       python3-networkx >= 3.0
Requires:       python3-rich >= 13.0

Recommends:     docker
Recommends:     python3-numpy
Recommends:     python3-scipy

%description
OpenForge EDA is an open-source electronic design automation platform
focused on cryptographic hardware verification. It provides a desktop
GUI application, command-line interface, REST API, and high-performance
Rust analysis tools for constant-time verification, side-channel analysis,
entropy analysis, HDL linting, and waveform viewing.

%prep
%autosetup -n %{name}-%{version}

%build
# Build Python wheels
mkdir -p dist
pip3 wheel --no-deps --wheel-dir dist/ \
    packages/core \
    packages/cli \
    packages/api \
    packages/desktop \
    packages/crypto

# Build Rust tools
export CARGO_HOME=%{_builddir}/.cargo
cargo build --release

# Build web frontend
cd packages/web
npm ci
npm run build
cd ../..

%install
# Create directory structure
mkdir -p %{buildroot}%{_bindir}
mkdir -p %{buildroot}%{_libdir}/openforge/venv
mkdir -p %{buildroot}%{_datadir}/openforge/web
mkdir -p %{buildroot}%{_datadir}/applications
mkdir -p %{buildroot}%{_datadir}/icons/hicolor/256x256/apps

# Install Python packages into a venv
python3 -m venv %{buildroot}%{_libdir}/openforge/venv --system-site-packages
%{buildroot}%{_libdir}/openforge/venv/bin/pip install --no-deps dist/*.whl

# Fix venv shebang paths for installed location
find %{buildroot}%{_libdir}/openforge/venv/bin -type f -exec \
    sed -i "s|%{buildroot}||g" {} \;

# Install CLI wrapper
cat > %{buildroot}%{_bindir}/openforge << 'WRAPPER'
#!/bin/sh
exec %{_libdir}/openforge/venv/bin/openforge "$@"
WRAPPER
chmod 755 %{buildroot}%{_bindir}/openforge

# Install desktop wrapper
cat > %{buildroot}%{_bindir}/openforge-desktop << 'WRAPPER'
#!/bin/sh
exec %{_libdir}/openforge/venv/bin/openforge-desktop "$@"
WRAPPER
chmod 755 %{buildroot}%{_bindir}/openforge-desktop

# Install Rust binaries
for tool in openforge-ct openforge-sca openforge-entropy openforge-lint openforge-wave; do
    if [ -f target/release/${tool} ]; then
        install -Dm755 target/release/${tool} %{buildroot}%{_bindir}/${tool}
    fi
done

# Install web assets
if [ -d packages/web/build ]; then
    cp -r packages/web/build/* %{buildroot}%{_datadir}/openforge/web/
fi

# Install desktop file
install -Dm644 installer/linux/openforge-eda.desktop \
    %{buildroot}%{_datadir}/applications/openforge-eda.desktop

# Install icon
if [ -f assets/openforge-256.png ]; then
    install -Dm644 assets/openforge-256.png \
        %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/openforge-eda.png
fi

%check
# Run Python unit tests
python3 -m pytest tests/unit/ -v --tb=short || :
# Run Rust tests
cargo test || :

%files
%license LICENSE
%doc README.md
%{_bindir}/openforge
%{_bindir}/openforge-desktop
%{_bindir}/openforge-ct
%{_bindir}/openforge-sca
%{_bindir}/openforge-entropy
%{_bindir}/openforge-lint
%{_bindir}/openforge-wave
%{_libdir}/openforge/
%{_datadir}/openforge/
%{_datadir}/applications/openforge-eda.desktop
%{_datadir}/icons/hicolor/256x256/apps/openforge-eda.png

%changelog
* Sat Apr 05 2026 Dyber Inc. <engineering@dyber.io> - 0.1.0-1
- Initial package release
- Core Python packages: openforge-core, openforge-cli, openforge-api,
  openforge-desktop, openforge-crypto
- Rust analysis tools: openforge-ct, openforge-sca, openforge-entropy,
  openforge-lint, openforge-wave
- Web frontend assets
- Desktop application with PySide6/Qt
