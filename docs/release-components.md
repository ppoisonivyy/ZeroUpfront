# Release container components

This snapshot covers the tested Debian Bookworm arm64 release with Python 3.12.16. The build uses Node 24 to compile the browser bundle and mounts uv for dependency installation. Rebuild this inventory for another image or architecture. The image installs the Python runtime under /usr/local in addition to the Debian packages below.

The base image includes pip 25.0.1 under /usr/local. Its CPython license is in `/usr/local/lib/python3.12/LICENSE.txt`. ReportLab ships additional font notices for Bitstream Vera and DarkGarden under `reportlab/fonts/` in the virtual environment.

## Debian packages · 105

| Package | Installed version | Notice path inside the image |
| --- | --- | --- |
| adduser | 3.134 | `/usr/share/doc/adduser/copyright` |
| apt | 2.6.2 | `/usr/share/doc/apt/copyright` |
| base-files | 12.4+deb12u15 | `/usr/share/doc/base-files/copyright` |
| base-passwd | 3.6.1 | `/usr/share/doc/base-passwd/copyright` |
| bash | 5.2.15-2+b13 | `/usr/share/doc/bash/copyright` |
| bsdutils | 1:2.38.1-5+deb12u3 | `/usr/share/doc/bsdutils/copyright` |
| ca-certificates | 20250419~deb12u2 | `/usr/share/doc/ca-certificates/copyright` |
| coreutils | 9.1-1 | `/usr/share/doc/coreutils/copyright` |
| dash | 0.5.12-2 | `/usr/share/doc/dash/copyright` |
| debconf | 1.5.82 | `/usr/share/doc/debconf/copyright` |
| debian-archive-keyring | 2023.3+deb12u2 | `/usr/share/doc/debian-archive-keyring/copyright` |
| debianutils | 5.7-0.5~deb12u1 | `/usr/share/doc/debianutils/copyright` |
| diffutils | 1:3.8-4 | `/usr/share/doc/diffutils/copyright` |
| dpkg | 1.21.23 | `/usr/share/doc/dpkg/copyright` |
| e2fsprogs | 1.47.0-2+b2 | `/usr/share/doc/e2fsprogs/copyright` |
| findutils | 4.9.0-4 | `/usr/share/doc/findutils/copyright` |
| gcc-12-base:arm64 | 12.2.0-14+deb12u1 | `/usr/share/doc/gcc-12-base/copyright` |
| gpgv | 2.2.40-1.1+deb12u2 | `/usr/share/doc/gpgv/copyright` |
| grep | 3.8-5 | `/usr/share/doc/grep/copyright` |
| gzip | 1.12-1 | `/usr/share/doc/gzip/copyright` |
| hostname | 3.23+nmu1 | `/usr/share/doc/hostname/copyright` |
| init-system-helpers | 1.65.2+deb12u1 | `/usr/share/doc/init-system-helpers/copyright` |
| libacl1:arm64 | 2.3.1-3 | `/usr/share/doc/libacl1/copyright` |
| libapt-pkg6.0:arm64 | 2.6.2 | `/usr/share/doc/libapt-pkg6.0/copyright` |
| libattr1:arm64 | 1:2.5.1-4 | `/usr/share/doc/libattr1/copyright` |
| libaudit-common | 1:3.0.9-1 | `/usr/share/doc/libaudit-common/copyright` |
| libaudit1:arm64 | 1:3.0.9-1 | `/usr/share/doc/libaudit1/copyright` |
| libblkid1:arm64 | 2.38.1-5+deb12u3 | `/usr/share/doc/libblkid1/copyright` |
| libbz2-1.0:arm64 | 1.0.8-5+b1 | `/usr/share/doc/libbz2-1.0/copyright` |
| libc-bin | 2.36-9+deb12u14 | `/usr/share/doc/libc-bin/copyright` |
| libc6:arm64 | 2.36-9+deb12u14 | `/usr/share/doc/libc6/copyright` |
| libcap-ng0:arm64 | 0.8.3-1+b3 | `/usr/share/doc/libcap-ng0/copyright` |
| libcap2:arm64 | 1:2.66-4+deb12u3+b1 | `/usr/share/doc/libcap2/copyright` |
| libcom-err2:arm64 | 1.47.0-2+b2 | `/usr/share/doc/libcom-err2/copyright` |
| libcrypt1:arm64 | 1:4.4.33-2 | `/usr/share/doc/libcrypt1/copyright` |
| libdb5.3:arm64 | 5.3.28+dfsg2-1 | `/usr/share/doc/libdb5.3/copyright` |
| libdebconfclient0:arm64 | 0.270 | `/usr/share/doc/libdebconfclient0/copyright` |
| libext2fs2:arm64 | 1.47.0-2+b2 | `/usr/share/doc/libext2fs2/copyright` |
| libffi8:arm64 | 3.4.4-1 | `/usr/share/doc/libffi8/copyright` |
| libgcc-s1:arm64 | 12.2.0-14+deb12u1 | `/usr/share/doc/libgcc-s1/copyright` |
| libgcrypt20:arm64 | 1.10.1-3+deb12u1 | `/usr/share/doc/libgcrypt20/copyright` |
| libgdbm6:arm64 | 1.23-3 | `/usr/share/doc/libgdbm6/copyright` |
| libgmp10:arm64 | 2:6.2.1+dfsg1-1.1 | `/usr/share/doc/libgmp10/copyright` |
| libgnutls30:arm64 | 3.7.9-2+deb12u7 | `/usr/share/doc/libgnutls30/copyright` |
| libgpg-error0:arm64 | 1.46-1 | `/usr/share/doc/libgpg-error0/copyright` |
| libgssapi-krb5-2:arm64 | 1.20.1-2+deb12u5 | `/usr/share/doc/libgssapi-krb5-2/copyright` |
| libhogweed6:arm64 | 3.8.1-2 | `/usr/share/doc/libhogweed6/copyright` |
| libidn2-0:arm64 | 2.3.3-1+b1 | `/usr/share/doc/libidn2-0/copyright` |
| libk5crypto3:arm64 | 1.20.1-2+deb12u5 | `/usr/share/doc/libk5crypto3/copyright` |
| libkeyutils1:arm64 | 1.6.3-2 | `/usr/share/doc/libkeyutils1/copyright` |
| libkrb5-3:arm64 | 1.20.1-2+deb12u5 | `/usr/share/doc/libkrb5-3/copyright` |
| libkrb5support0:arm64 | 1.20.1-2+deb12u5 | `/usr/share/doc/libkrb5support0/copyright` |
| liblz4-1:arm64 | 1.9.4-1 | `/usr/share/doc/liblz4-1/copyright` |
| liblzma5:arm64 | 5.4.1-1+deb12u2 | `/usr/share/doc/liblzma5/copyright` |
| libmd0:arm64 | 1.0.4-2 | `/usr/share/doc/libmd0/copyright` |
| libmount1:arm64 | 2.38.1-5+deb12u3 | `/usr/share/doc/libmount1/copyright` |
| libncursesw6:arm64 | 6.4-4 | `/usr/share/doc/libncursesw6/copyright` |
| libnettle8:arm64 | 3.8.1-2 | `/usr/share/doc/libnettle8/copyright` |
| libnsl2:arm64 | 1.3.0-2 | `/usr/share/doc/libnsl2/copyright` |
| libp11-kit0:arm64 | 0.24.1-2 | `/usr/share/doc/libp11-kit0/copyright` |
| libpam-modules-bin | 1.5.2-6+deb12u2 | `/usr/share/doc/libpam-modules-bin/copyright` |
| libpam-modules:arm64 | 1.5.2-6+deb12u2 | `/usr/share/doc/libpam-modules/copyright` |
| libpam-runtime | 1.5.2-6+deb12u2 | `/usr/share/doc/libpam-runtime/copyright` |
| libpam0g:arm64 | 1.5.2-6+deb12u2 | `/usr/share/doc/libpam0g/copyright` |
| libpcre2-8-0:arm64 | 10.42-1+deb12u2 | `/usr/share/doc/libpcre2-8-0/copyright` |
| libreadline8:arm64 | 8.2-1.3 | `/usr/share/doc/libreadline8/copyright` |
| libseccomp2:arm64 | 2.5.4-1+deb12u1 | `/usr/share/doc/libseccomp2/copyright` |
| libselinux1:arm64 | 3.4-1+b6 | `/usr/share/doc/libselinux1/copyright` |
| libsemanage-common | 3.4-1 | `/usr/share/doc/libsemanage-common/copyright` |
| libsemanage2:arm64 | 3.4-1+b5 | `/usr/share/doc/libsemanage2/copyright` |
| libsepol2:arm64 | 3.4-2.1 | `/usr/share/doc/libsepol2/copyright` |
| libsmartcols1:arm64 | 2.38.1-5+deb12u3 | `/usr/share/doc/libsmartcols1/copyright` |
| libsqlite3-0:arm64 | 3.40.1-2+deb12u2 | `/usr/share/doc/libsqlite3-0/copyright` |
| libss2:arm64 | 1.47.0-2+b2 | `/usr/share/doc/libss2/copyright` |
| libssl3:arm64 | 3.0.22-1~deb12u2 | `/usr/share/doc/libssl3/copyright` |
| libstdc++6:arm64 | 12.2.0-14+deb12u1 | `/usr/share/doc/libstdc++6/copyright` |
| libsystemd0:arm64 | 252.39-1~deb12u2 | `/usr/share/doc/libsystemd0/copyright` |
| libtasn1-6:arm64 | 4.19.0-2+deb12u1 | `/usr/share/doc/libtasn1-6/copyright` |
| libtinfo6:arm64 | 6.4-4 | `/usr/share/doc/libtinfo6/copyright` |
| libtirpc-common | 1.3.3+ds-1 | `/usr/share/doc/libtirpc-common/copyright` |
| libtirpc3:arm64 | 1.3.3+ds-1 | `/usr/share/doc/libtirpc3/copyright` |
| libudev1:arm64 | 252.39-1~deb12u2 | `/usr/share/doc/libudev1/copyright` |
| libunistring2:arm64 | 1.0-2 | `/usr/share/doc/libunistring2/copyright` |
| libuuid1:arm64 | 2.38.1-5+deb12u3 | `/usr/share/doc/libuuid1/copyright` |
| libxxhash0:arm64 | 0.8.1-1 | `/usr/share/doc/libxxhash0/copyright` |
| libzstd1:arm64 | 1.5.4+dfsg2-5 | `/usr/share/doc/libzstd1/copyright` |
| login | 1:4.13+dfsg1-1+deb12u2 | `/usr/share/doc/login/copyright` |
| logsave | 1.47.0-2+b2 | `/usr/share/doc/logsave/copyright` |
| mawk | 1.3.4.20200120-3.1 | `/usr/share/doc/mawk/copyright` |
| mount | 2.38.1-5+deb12u3 | `/usr/share/doc/mount/copyright` |
| ncurses-base | 6.4-4 | `/usr/share/doc/ncurses-base/copyright` |
| ncurses-bin | 6.4-4 | `/usr/share/doc/ncurses-bin/copyright` |
| netbase | 6.4 | `/usr/share/doc/netbase/copyright` |
| openssl | 3.0.22-1~deb12u2 | `/usr/share/doc/openssl/copyright` |
| passwd | 1:4.13+dfsg1-1+deb12u2 | `/usr/share/doc/passwd/copyright` |
| perl-base | 5.36.0-7+deb12u4 | `/usr/share/doc/perl-base/copyright` |
| readline-common | 8.2-1.3 | `/usr/share/doc/readline-common/copyright` |
| sed | 4.9-1+deb12u1 | `/usr/share/doc/sed/copyright` |
| sysvinit-utils | 3.06-4 | `/usr/share/doc/sysvinit-utils/copyright` |
| tar | 1.34+dfsg-1.2+deb12u1 | `/usr/share/doc/tar/copyright` |
| tzdata | 2026f-0+deb12u1 | `/usr/share/doc/tzdata/copyright` |
| usr-is-merged | 37~deb12u1 | `/usr/share/doc/usr-is-merged/copyright` |
| util-linux | 2.38.1-5+deb12u3 | `/usr/share/doc/util-linux/copyright` |
| util-linux-extra | 2.38.1-5+deb12u3 | `/usr/share/doc/util-linux-extra/copyright` |
| zlib1g:arm64 | 1:1.2.13.dfsg-1 | `/usr/share/doc/zlib1g/copyright` |

## Native libraries shipped inside Python wheels

These shared objects are present outside Debian's package database. The containing wheel identifies the distribution that supplies the binary.

| Wheel directory | Library file |
| --- | --- |
| pillow.libs | libXau-7926f62a.so.6.0.0 |
| pillow.libs | libavif-ba04b566.so.16.4.2 |
| pillow.libs | libbrotlicommon-f79e5820.so.1.2.0 |
| pillow.libs | libbrotlidec-53ab751a.so.1.2.0 |
| pillow.libs | libfreetype-6d43b1fe.so.6.20.6 |
| pillow.libs | libharfbuzz-38f28207.so.0.61450.0 |
| pillow.libs | libjpeg-80045241.so.62.4.0 |
| pillow.libs | liblcms2-4345ab8b.so.2.0.19 |
| pillow.libs | liblzma-dcd007de.so.5.8.4 |
| pillow.libs | libopenjp2-4495a901.so.2.5.4 |
| pillow.libs | libpng16-76a95936.so.16.58.0 |
| pillow.libs | libsharpyuv-5dac68d0.so.0.1.2 |
| pillow.libs | libtiff-0c352bdc.so.6.3.0 |
| pillow.libs | libwebp-bac0fc6b.so.7.2.0 |
| pillow.libs | libwebpdemux-b0a60f8c.so.2.0.17 |
| pillow.libs | libwebpmux-fec2c160.so.3.1.2 |
| pillow.libs | libxcb-cbbede0a.so.1.1.0 |
| pillow.libs | libzstd-79fd2b21.so.1.5.7 |
| psycopg_binary.libs | libcom_err-6d8d18aa.so.2.1 |
| psycopg_binary.libs | libcom_err-ade663e2.so.3.0 |
| psycopg_binary.libs | libcrypt-258f54d5.so.1.1.0 |
| psycopg_binary.libs | libcrypto-5e36fb0e.so.3 |
| psycopg_binary.libs | libgssapi_krb5-2d78fad2.so.2.2 |
| psycopg_binary.libs | libk5crypto-08068307.so.3.1 |
| psycopg_binary.libs | libkeyutils-fe6e95a9.so.1.6 |
| psycopg_binary.libs | libkrb5-138a6e7a.so.3.3 |
| psycopg_binary.libs | libkrb5support-bba7dd31.so.0.1 |
| psycopg_binary.libs | liblber-39a5c986.so.2.0.200 |
| psycopg_binary.libs | libldap-ed13728f.so.2.0.200 |
| psycopg_binary.libs | libpq-53e4e5f8.so.5.18 |
| psycopg_binary.libs | libsasl2-076b3c1f.so.3.0.0 |
| psycopg_binary.libs | libssl-8f8630a8.so.3 |

For embedded or statically linked code, consult the upstream Python distribution notices and browser resource licenses in the [component inventory](../THIRD_PARTY.md).
