//! Nonblocking ownership of one open file descriptor. Closing it releases the lock.
use std::{fs::File, io};

#[cfg(unix)]
pub fn try_lock_owner(file: &File) -> io::Result<()> {
    use std::os::fd::AsRawFd;
    // Rust 1.96's File::try_lock returns Unsupported on Android. Bionic has
    // flock(2) on our API 35 baseline. Exercise the same syscall on macOS/Linux.
    loop {
        // SAFETY: the live File owns the descriptor for the duration of this call.
        let rc = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) };
        if rc == 0 {
            return Ok(());
        }
        let error = io::Error::last_os_error();
        if error.kind() != io::ErrorKind::Interrupted {
            return Err(error);
        }
    }
}

#[cfg(not(unix))]
pub fn try_lock_owner(file: &File) -> io::Result<()> {
    file.try_lock().map_err(Into::into)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs::OpenOptions;

    #[test]
    fn another_descriptor_is_refused_until_the_owner_closes() {
        let path = std::env::temp_dir().join(format!(
            "pocket-lock-{}-{}", std::process::id(), crate::pairing::random_public_id().unwrap()
        ));
        let first = OpenOptions::new().create_new(true).read(true).write(true).open(&path).unwrap();
        let second = OpenOptions::new().read(true).write(true).open(&path).unwrap();
        try_lock_owner(&first).unwrap();
        assert_eq!(try_lock_owner(&second).unwrap_err().kind(), io::ErrorKind::WouldBlock);
        drop(first);
        try_lock_owner(&second).unwrap();
        drop(second);
        std::fs::remove_file(path).unwrap();
    }
}
