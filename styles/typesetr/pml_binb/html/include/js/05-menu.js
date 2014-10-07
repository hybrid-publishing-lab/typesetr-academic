  $(document).ready(function(e){
  // loop through each chapter title and place a footnote wrapper before it
    $('h1').each(function(key,elm){
        var _key = key+1;
        
        $(this).before('<p class="real_footnotes" />');
        
        // create the anchor point
        var aname = $('<a />');
            aname.attr('name','chapter' + _key);
        $(this).before( aname );

        
        // create the link/placeholder
        var li = $('<li />');
        var ahref = $('<a />');
            ahref.attr('href','#chapter' + _key);
            ahref.text( $(this).text() );
        
        li.html( ahref );
        
        // replace the original footnote with the placeholder
        $('.contents').append( li );        
    });
});