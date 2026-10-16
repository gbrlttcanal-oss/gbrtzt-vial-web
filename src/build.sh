#!/bin/bash

set -e

source ../version.sh
source ../emsdk/emsdk_env.sh

mkdir -p build
rm -rf build/*

pushd build

# The Vial app is vendored under vialgui/; its version is the last commit that touched it
VIAL_VER=$(git log -1 --format=%H -- ../../vialgui)
WEB_VER=$(git rev-parse HEAD)
VIA_STACK_VER=$(cd ../../via-keymap-precompiled/ && git rev-parse HEAD)
UNIQVER=$(echo ${VIAL_VER} ${WEB_VER} ${VIA_STACK_VER} | sha256sum | awk '{print $1}')

cp ../icon.png .
cp -r ../../deps/cpython/builddir/emscripten-browser/usr .
cp ../../via-keymap-precompiled/via_keyboard_stack.json usr/local/via_keyboards.json
cp ../../vialgui/qmk_settings.json usr/local
cp ../../vialgui/build_settings.json usr/local
cp -r ../../vialgui/python/* usr/local/lib/python3.11
find usr/local/lib/python3.11 -name __pycache__ -type d -prune -exec rm -rf {} +
cp ../simpleeval.py usr/local/lib/python3.11
# Firmware catalogue: the manifest is preloaded so the Updates tab can read it like the other JSON
# resources; the .uf2 files stay outside the bundle and are fetched/downloaded as plain files.
cp ../../firmware/manifest.json usr/local/firmware_manifest.json
# Demo mode (*Try the demo* on the start page): recorded boards, made by demo/capture-demo.py
mkdir -p usr/local/demo
cp ../../demo/*.json usr/local/demo/
emcc \
    --preload-file="./usr/local" \
    -I ../../deps/cpython/Include/ \
    -I ../../deps/cpython/builddir/emscripten-browser/ \
    -I ../../deps/cpython/Include/internal/ \
    ../../deps/cpython/builddir/emscripten-browser/libpython3.11.a \
    ../../deps/cpython/builddir/emscripten-browser/Modules/_decimal/libmpdec/libmpdec.a \
    ../../deps/cpython/builddir/emscripten-browser/Modules/expat/libexpat.a  \
    -sALLOW_MEMORY_GROWTH \
    -sTOTAL_MEMORY=20971520 \
    -sFORCE_FILESYSTEM \
    -sTEXTDECODER=0 \
    -lidbfs.js \
    -lnodefs.js \
    -lproxyfs.js \
    -lworkerfs.js \
    -O2 -g0 \
    -o main-${UNIQVER}.js \
    -ldl \
    -lm \
    -sUSE_ZLIB \
    -sUSE_BZIP2 \
    -sUSE_ZLIB \
    -L ../../deps/PyQt5-${PYQT5_VER}/QtCore \
    -L ../../deps/qt5/qtbase/lib \
    -L ../../deps/PyQt5_sip-${PYQT5SIP_VER} \
    -L ../../deps/PyQt5-${PYQT5_VER}/QtGui \
    -L ../../deps/PyQt5-${PYQT5_VER}/QtWidgets \
    -L ../../deps/qt5/qtbase/plugins/platforms \
    -L ../../deps/PyQt5-${PYQT5_VER}/QtSvg \
    -L ../../deps/qt5/qtbase/plugins/iconengines \
    -L ../../deps/qt5/qtbase/plugins/imageformats \
    -l QtCore \
    -l Qt5Core \
    -l sip \
    -l QtGui \
    -l QtWidgets \
    -l Qt5Core \
    -l Qt5Gui \
    -l Qt5Widgets \
    -l qwasm \
    -l Qt5FontDatabaseSupport \
    -l qminimal \
    -l Qt5EventDispatcherSupport \
    -l qoffscreen \
    --bind \
    -l qtharfbuzz \
    -l QtSvg \
    -l qsvgicon \
    -l qjpeg \
    -l qsvg \
    -l Qt5Svg \
    -s USE_FREETYPE=1 \
    -s USE_LIBPNG=1 \
    -lqtpcre2 \
    -pthread \
    -sDISABLE_DEPRECATED_FIND_EVENT_TARGET_BEHAVIOR=0 \
    -s EXTRA_EXPORTED_RUNTIME_METHODS=\["UTF16ToString","stringToUTF16","getValue","setValue"\] \
    -sEXPORTED_FUNCTIONS=\["_PyRun_SimpleString","_vialglue_set_response","_vialglue_set_response_error","_vialglue_set_device_desc","_main"\] \
    -sPROXY_TO_PTHREAD \
    -sOFFSCREENCANVAS_SUPPORT \
    -L ../../deps/xz-${XZ_VER}/prefix/lib/ \
    -llzma \
    ../main.c
cp ../index.html .
cp ../gbrtzt-logo.png .
cp ../coi-serviceworker.js .
cp -r ../flash .
mkdir -p firmware
cp ../../firmware/manifest.json ../../firmware/*.uf2 firmware/
cat ../worker.js >> main-${UNIQVER}.worker.js
sed -i 's+err("worker sent an unknown command+my_onmessage(e);return;err("worker sent an unknown command/+g' main-${UNIQVER}.js

rm -rf usr

sed -i "s/@VIAL_VER@/${VIAL_VER}/g" index.html
sed -i "s/@WEB_VER@/${WEB_VER}/g" index.html
sed -i "s/@VIA_STACK_VER@/${VIA_STACK_VER}/g" index.html
sed -i "s/@UNIQVER@/${UNIQVER}/g" index.html

popd
