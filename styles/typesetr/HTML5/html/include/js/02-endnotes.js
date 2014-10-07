(function() {
  /*
  Originally:
  jQuery Inline Endnotes v1.0
  Released under the MIT License.
  https://github.com/vesan/jquery-inline-footnotes

  Modified with better event handling, touch device support and renamed for our purposes.
  */
  var __bind = function(fn, me){ return function(){ return fn.apply(me, arguments); }; };
  (function($) {
    $.inlineEndnote = function(el, options) {
      this.el = $(el);
      this.el.data("inlineEndnote", this);
      this.initialize = function() {
        this.options = $.extend({}, $.inlineEndnote.defaultOptions, options);
        
        $(this.options.hideEntirely).hide();

        this.endnoteId = this.el.attr("href").match(/#(.*)/)[1];
        if (this.endnoteId) {
          this.el.on("click", this.openModal);
        }
      };

      this.openModal = __bind(function(event) {
        event.stopPropagation();
        var endnote, endnoteContent, linkOffset;
        if (!this.modal) {
          endnote = $("[id='" + this.endnoteId + "']");
          endnoteContent = endnote.children().not(this.options.hideFromContent);
          if (endnoteContent.length == 0) {
            endnoteContent = $('<p/>', { html: endnote.text() });
          }
          linkOffset = this.el.offset();
          this.modal = $("<div />", {
            id: this.options.modalId,
            html: endnoteContent.clone(),
            css: {
              position: "absolute",
              top: linkOffset.top,
              left: linkOffset.left + this.el.outerWidth()
            }
          }).appendTo("body");
          $(document).on("click touchstart", this.closeModal);
          return this.positionModal();
        }
      }, this);

      this.closeModal = __bind(function(event) {
        if (this.modal) {
          if (this.isHoveringEndnote(event)) {
            clearTimeout(this.closeTimeout);
            return this.closeTimeout = null;
          } else {
            if (!this.closeTimeout) {
              $(document).unbind("click mousemove touchstart");
              return this.closeTimeout = setTimeout((__bind(function() {
                this.modal.remove();
                this.closeTimeout = null;
                return this.modal = null;
              }, this)), this.options.hideDelay);
            }
          }
        }
      }, this);

      this.isHoveringEndnote = function(event) {
        return this.modal.is(event.target) || $(event.target).closest(this.modal).length > 0 || event.target === this.el[0];
      };

      this.positionModal = function() {
        var boxLeft, boxWidth, linkLeftOffset, modalHorizontalPadding, windowWidth;
        modalHorizontalPadding = parseInt(this.modal.css("padding-left")) + parseInt(this.modal.css("padding-right"));
        linkLeftOffset = this.el.offset().left;
        windowWidth = $(window).width();
        if ((windowWidth / 2) > linkLeftOffset) {
          boxLeft = linkLeftOffset + 20;
          boxWidth = windowWidth - boxLeft - modalHorizontalPadding - this.options.boxMargin * 2;
          if (boxWidth > this.options.maximumBoxWidth) {
            boxWidth = this.options.maximumBoxWidth;
          }
        } else {
          boxWidth = linkLeftOffset - modalHorizontalPadding - this.options.boxMargin * 2;
          if (boxWidth > this.options.maximumBoxWidth) {
            boxWidth = this.options.maximumBoxWidth;
          }
          boxLeft = linkLeftOffset - boxWidth - this.options.boxMargin * 2;
        }
        return this.modal.css({
          width: boxWidth,
          left: boxLeft
        });
      };
      return this.initialize();
    };

    $.inlineEndnote.defaultOptions = {
      boxMargin: 20,
      hideDelay: 200,
      hideFromContent: "[rev=endnote]",
      //hideEntirely: "section.endnotes",
      maximumBoxWidth: 500,
      modalId: "endnote-box"
    };

    return $.fn.inlineEndnote = function(options) {
      return this.each(function() {
        return new $.inlineEndnote(this, options);
      });
    };
  })(jQuery);
}).call(this);

$(function() {
  // Progressively enhance endnote functionality, to hide the endnotes asides,
  // and show inline hover popups instead.
  $(".noteref").inlineEndnote();
});
