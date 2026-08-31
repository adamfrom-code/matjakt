/* Landningssidans film.
 *
 * Three rules, in priority order:
 *
 * 1. THE PAGE NEVER WAITS FOR VIDEO. Nothing here runs before the page has
 *    rendered, no clip has a src until it is needed, and every failure path
 *    ends with the poster still showing. A marketing page that is blank while
 *    4 MB downloads has already lost the visitor.
 * 2. THE VISITOR DECIDES. Data Saver or prefers-reduced-motion means stills,
 *    not motion - both are people telling us something, and a background
 *    video is exactly the kind of thing they are turning off.
 * 3. OFF-SCREEN CLIPS DO NOT PLAY. A phone decoding six videos at once gets
 *    hot and slow for footage nobody is looking at.
 */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  var saveData = !!(connection && connection.saveData);
  // 2g/slow-2g is not a connection to send video over, whatever the visitor
  // has asked for.
  var slowNetwork = !!(connection && /(^|-)2g$/.test(connection.effectiveType || ""));

  if (reduceMotion || saveData || slowNetwork) {
    // The posters are already in the markup, so there is nothing to do: the
    // page stays exactly as it rendered, as stills.
    document.documentElement.setAttribute("data-video", "still");
    return;
  }
  document.documentElement.setAttribute("data-video", "motion");

  // play() rejects on its own whenever a browser decides not to autoplay.
  // That is a normal outcome, not an error - the poster stays up.
  function play(video) {
    var attempt = video.play();
    if (attempt && attempt.catch) attempt.catch(function () {});
  }

  function load(video, src) {
    if (video.dataset.loaded) return;
    video.dataset.loaded = "1";
    video.src = src;
    video.load();
  }

  /* --- Hero: two clips, crossfading -------------------------------------
   * The second clip only loads once the first is actually playing, so the
   * hero costs one clip until it has something to show for the second.      */
  var heroClips = [].slice.call(document.querySelectorAll("[data-hero-clip]"));
  if (heroClips.length) {
    var sources = ["site/video/matjakt-hero.mp4", "site/video/matjakt-vecka.mp4"];
    load(heroClips[0], sources[0]);
    play(heroClips[0]);

    if (heroClips.length > 1) {
      heroClips[0].addEventListener("playing", function once() {
        heroClips[0].removeEventListener("playing", once);
        load(heroClips[1], sources[1]);
        play(heroClips[1]);
        var active = 0;
        setInterval(function () {
          if (document.hidden) return;
          heroClips[active].classList.remove("is-active");
          active = (active + 1) % heroClips.length;
          heroClips[active].classList.add("is-active");
          play(heroClips[active]);
        }, 7000);
      });
    }
  }

  /* --- Presentation: load and play only what is on screen ---------------- */
  var filmClips = [].slice.call(document.querySelectorAll("[data-film-src]"));
  if (!filmClips.length) return;

  if (!("IntersectionObserver" in window)) {
    // Old browser: posters only. Loading all six would be the worse failure.
    return;
  }

  // rootMargin gives the clip a head start, so it is decoded by the time the
  // scene is actually in view rather than starting with a visible stall.
  var observer = new IntersectionObserver(function (entries) {
    entries.forEach(function (entry) {
      var video = entry.target;
      if (entry.isIntersecting) {
        load(video, video.dataset.filmSrc);
        video.closest(".site-film-scene").classList.add("is-visible");
        play(video);
      } else if (video.dataset.loaded) {
        video.pause();
      }
    });
  }, { rootMargin: "200px 0px", threshold: 0.25 });

  filmClips.forEach(function (video) { observer.observe(video); });

  // A backgrounded tab should not keep decoding video.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) return;
    filmClips.concat(heroClips).forEach(function (video) {
      if (video.dataset.loaded) video.pause();
    });
  });
})();
