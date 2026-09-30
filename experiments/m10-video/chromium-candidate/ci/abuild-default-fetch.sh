# Unchanged default_fetch function from Alpine abuild master.in.
# Commit: 03444ca1b6fa10d1717d024a6e94ee27e3ed50f2
# https://github.com/alpinelinux/abuild/blob/03444ca1b6fa10d1717d024a6e94ee27e3ed50f2/abuild.in
# Copyright (c) 2008-2015 Natanael Copa <ncopa@alpinelinux.org>
# Copyright (c) 2016 Timo Teras <timo.teras@iki.fi>
# Distributed under GPL-2.0-only; retained solely for offline regression fixtures.
default_fetch() {
	local s
	mkdir -p "$srcdir"
	set -- ${sha512sums:-$sha256sums}

	for s in $source; do
		local file="$startdir/$s"
		if is_remote "$s"; then
			uri_fetch_mirror "$s" || return 1
			file="$SRCDEST/$(filename_from_uri $s)"
		fi

		if [ "$sumalgo" != none ]; then
			if ! echo "$1  $file" | ${sumalgo}sum -c; then
				if is_remote $s; then
					csum="${1:0:8}"

					echo "Because the remote file above failed the ${sumalgo}sum check it will be renamed."
					echo "Rebuilding will cause it to re-download which in some cases may fix the problem."
					echo "Renaming: ${file##*/} to ${file##*/}.$csum"
					mv "$file" "$file.$csum"
				fi
				die "Use 'abuild checksum' to generate/update the checksum(s)"
			fi
			shift 2
		fi

		ln -sf "$file" "$srcdir/"
	done
}
